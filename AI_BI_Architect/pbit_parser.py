#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Power BI (.pbit) şablon dosyasını okuyup analiz edilebilir metadata'ya çevirir.

Çıkarılan bilgiler:
  * DataModelSchema  -> tablolar, kolonlar, measure'lar, ilişkiler, partition/sorgu bilgisi
  * Report/Layout    -> sayfalar, görseller, hangi alanın hangi görselde kullanıldığı
  * profile          -> ilişki kardinalitesinden türetilen fact/dimension rolleri

`get_clean_data()` sözlüğü, eski sürümdeki anahtarları (tables/rels/measures/...)
koruyarak üzerine yapısal alanlar ekler.
"""

import zipfile
import json
import re
from collections import Counter, defaultdict

# TMSL varsayılanları: alan yazılmamışsa Power BI bu değerleri kullanır.
DEFAULT_FROM_CARDINALITY = "many"
DEFAULT_TO_CARDINALITY = "one"
DEFAULT_CROSS_FILTER = "oneDirection"

NUMERIC_NAME_TOKENS = (
    'id', 'no', 'number', 'num', 'code', 'kod', 'year', 'month', 'day',
    'tutar', 'amount', 'price', 'fiyat', 'miktar', 'sayi', 'sayı', 'count', 'adet', 'oran',
)
NUMERIC_TYPES = ('int64', 'double', 'decimal')


def normalize_expression(value, limit=None):
    """TMSL ifadeleri string ya da satır listesi olabilir; ikisini de metne çevirir."""
    if value is None:
        text = ""
    elif isinstance(value, str):
        text = value
    elif isinstance(value, (list, tuple)):
        text = "\n".join(str(part) for part in value)
    else:
        text = json.dumps(value, ensure_ascii=False)

    # Power Query sorguları satır sonlarını #(lf) olarak kaçırıyor.
    text = text.replace('#(lf)', '\n').replace('#(tab)', '\t')
    if limit and len(text) > limit:
        text = text[:limit]
    return text


TR_FOLD_MAP = str.maketrans({
    'ş': 's', 'Ş': 's', 'ı': 'i', 'İ': 'i', 'ğ': 'g', 'Ğ': 'g',
    'ü': 'u', 'Ü': 'u', 'ö': 'o', 'Ö': 'o', 'ç': 'c', 'Ç': 'c',
    'â': 'a', 'î': 'i', 'û': 'u',
})


def fold_name(name):
    """Türkçe karakter ve ayırıcıları normalize eder.

    'Şikayet Tarihi' ve 'SikayetTarihi' aynı anahtara iner; böylece tablolar
    arasında isim eşleştirmesi yapılabilir.
    """
    folded = (name or "").translate(TR_FOLD_MAP).lower()
    for char in (' ', '_', '-', '.', '[', ']'):
        folded = folded.replace(char, '')
    return folded


def name_tokens(name):
    """'SikayetTarihi' -> ['sikayet', 'tarihi'], 'Ayın Son Günü' -> ['ayin', 'son', 'gunu']."""
    text = re.sub(r'([a-zçğıöşü])([A-ZÇĞİÖŞÜ])', r'\1 \2', name or "")
    text = text.translate(TR_FOLD_MAP).lower()
    return [tok for tok in re.split(r'[^a-z0-9]+', text) if tok]


# Değeri gerçek bir tarih/zaman olması gereken kolon adları (string ise sorun)
STRONG_DATE_PREFIXES = ('tarih', 'date', 'datetime', 'timestamp', 'zaman')
# Zaman eksenini ifade eden ama metin olabilen parçalar (ay adı, gün adı, dönem)
DATE_PART_WORDS = {
    'ay', 'ayi', 'ayin', 'aylik', 'yil', 'yili', 'yilin', 'gun', 'gunu', 'gunun', 'gunluk',
    'hafta', 'haftasi', 'saat', 'donem', 'ceyrek', 'day', 'month', 'year', 'week', 'hour',
    'quarter', 'period', 'time', 'qtr',
}


def is_date_value_name(name):
    """Kolon adı bir tarih DEĞERİ taşıdığını söylüyor mu? (örn. SikayetTarihi, OrderDate)"""
    return any(tok.startswith(STRONG_DATE_PREFIXES) for tok in name_tokens(name))


def is_dateish_name(name):
    """Kolon zaman ekseniyle ilgili mi? (tarih değeri, ay/gün/dönem etiketi dahil)"""
    tokens = name_tokens(name)
    return any(tok.startswith(STRONG_DATE_PREFIXES) or tok in DATE_PART_WORDS for tok in tokens)


def looks_numeric_name(name):
    tokens = name_tokens(name)
    return any(tok in NUMERIC_NAME_TOKENS for tok in tokens)


class PBITParser:
    def __init__(self, file_path):
        self.file_path = file_path

    # ------------------------------------------------------------------ zip
    def _decode_json_from_zip(self, zip_file, name):
        raw = zip_file.read(name)
        for encoding in ("utf-16-le", "utf-8", "utf-16", "latin-1"):
            try:
                return json.loads(raw.decode(encoding))
            except Exception:
                continue
        raise ValueError(f"Unable to decode {name}")

    def _strip_literal(self, value):
        if isinstance(value, str) and len(value) >= 2 and value.startswith("'") and value.endswith("'"):
            return value[1:-1]
        return value

    # --------------------------------------------------------------- tables
    def _parse_column(self, raw_column):
        col_type = raw_column.get('type')
        return {
            # Eski anahtarlar (geriye dönük uyumluluk)
            "n": raw_column['name'],
            "t": raw_column.get('dataType'),
            "hidden": raw_column.get('isHidden', False),
            # Yeni yapısal alanlar
            "name": raw_column['name'],
            "data_type": raw_column.get('dataType'),
            "kind": col_type or 'data',
            "is_calculated": col_type in ('calculated', 'calculatedTableColumn'),
            "expression": normalize_expression(raw_column.get('expression')),
            "summarize_by": raw_column.get('summarizeBy'),
            "format_string": raw_column.get('formatString'),
            "data_category": raw_column.get('dataCategory'),
            "sort_by_column": raw_column.get('sortByColumn'),
            "is_key": raw_column.get('isKey', False),
        }

    def _parse_measure(self, raw_measure, table_name):
        full_formula = normalize_expression(raw_measure.get('expression'))
        return {
            "name": raw_measure['name'],
            "table": table_name,
            # Eski davranış: kısaltılmış formül
            "formula": full_formula[:200],
            # Analiz için tam formül
            "formula_full": full_formula,
            "hidden": raw_measure.get('isHidden', False),
            "format_string": raw_measure.get('formatString'),
            "display_folder": raw_measure.get('displayFolder'),
        }

    def _parse_partitions(self, raw_table):
        partitions = []
        for part in raw_table.get('partitions', []) or []:
            source = part.get('source', {}) or {}
            partitions.append({
                "name": part.get('name'),
                "mode": part.get('mode', 'import'),
                "source_type": source.get('type'),
                "expression": normalize_expression(source.get('expression')),
            })
        return partitions

    def _is_auto_date_table(self, raw_table, partitions):
        """Power BI'ın otomatik ürettiği gizli tarih tablosu mu?

        Bunlar gerçek bir Calendar dimension sayılmaz: gizli/private'tır,
        ilişkisi raporlanmaz ve kullanıcı modeline girmez.
        """
        name = raw_table.get('name', '')
        if name.startswith('DateTableTemplate_') or name.startswith('LocalDateTable_'):
            return True
        if not raw_table.get('isPrivate'):
            return False
        for part in partitions:
            if part['source_type'] == 'calculated' and 'calendar' in (part['expression'] or '').lower():
                return True
        return False

    # -------------------------------------------------------- relationships
    def _parse_relationship(self, raw_rel):
        from_cardinality = raw_rel.get('fromCardinality', DEFAULT_FROM_CARDINALITY)
        to_cardinality = raw_rel.get('toCardinality', DEFAULT_TO_CARDINALITY)
        cross_filter = raw_rel.get('crossFilteringBehavior', DEFAULT_CROSS_FILTER)
        is_many_to_many = from_cardinality == 'many' and to_cardinality == 'many'
        return {
            "name": raw_rel.get('name'),
            "from_table": raw_rel.get('fromTable'),
            "from_col": raw_rel.get('fromColumn'),
            "to_table": raw_rel.get('toTable'),
            "to_col": raw_rel.get('toColumn'),
            "from_cardinality": from_cardinality,
            "to_cardinality": to_cardinality,
            "cross_filter": cross_filter,
            "is_active": raw_rel.get('isActive', True),
            "is_many_to_many": is_many_to_many,
            "is_one_to_one": from_cardinality == 'one' and to_cardinality == 'one',
            "is_bidirectional": cross_filter == 'bothDirections',
            "rely_on_referential_integrity": raw_rel.get('relyOnReferentialIntegrity', False),
            # Eski anahtar
            "type": raw_rel.get('type', f"{from_cardinality}-to-{to_cardinality}"),
        }

    # -------------------------------------------------------------- profile
    def _build_profile(self, tables, relationships):
        """Fact/dimension rollerini ilişki kardinalitesinden türetir.

        İsim tahmini yapmaz; sadece modelde hiç ilişki yoksa son çare olarak
        isim sezgisine düşer ve bunu `method` alanında bildirir.
        """
        by_name = {t['name']: t for t in tables}
        acts_many = defaultdict(list)
        acts_one = defaultdict(list)

        for rel in relationships:
            for table_key, cardinality_key in (('from_table', 'from_cardinality'), ('to_table', 'to_cardinality')):
                table_name = rel.get(table_key)
                if table_name not in by_name:
                    continue
                if rel.get(cardinality_key) == 'many':
                    acts_many[table_name].append(rel)
                else:
                    acts_one[table_name].append(rel)

        roles = {}
        for table in tables:
            name = table['name']
            if table['is_auto_date_table']:
                roles[name] = 'auto_date'
                continue
            many_count = len(acts_many.get(name, []))
            one_count = len(acts_one.get(name, []))
            if many_count and one_count:
                roles[name] = 'bridge'
            elif one_count:
                roles[name] = 'dimension'
            elif many_count:
                roles[name] = 'fact'
            else:
                roles[name] = 'isolated'

        method = 'cardinality'
        if not relationships:
            # Hiç ilişki yoksa kardinalite bilgi vermez; isim sezgisi son çare.
            method = 'name-fallback'
            for table in tables:
                name = table['name']
                if roles[name] != 'isolated':
                    continue
                lower = name.lower()
                if any(tok in lower for tok in ('fact', 'fct', 'veri', 'sales', 'satis', 'satış', 'transaction', 'hareket')):
                    roles[name] = 'fact?'
                elif any(tok in lower for tok in ('dim', 'lookup', 'musteri', 'müşteri', 'customer', 'urun', 'ürün', 'product')):
                    roles[name] = 'dimension?'

        date_dimensions = []
        unconnected_date_tables = []
        for table in tables:
            if not table['is_date_table_like']:
                continue
            if roles[table['name']] in ('dimension', 'bridge', 'dimension?'):
                date_dimensions.append(table['name'])
            elif roles[table['name']] in ('isolated', 'fact', 'fact?'):
                unconnected_date_tables.append(table['name'])

        def names_with_role(*wanted):
            return [t['name'] for t in tables if roles[t['name']] in wanted]

        facts = names_with_role('fact', 'fact?')
        dimensions = names_with_role('dimension', 'dimension?')

        # Fact tablolarındaki tarih kolonları bir tarih dimension'ına bağlı mı?
        date_linked_facts = set()
        for rel in relationships:
            if rel['to_table'] in date_dimensions and rel['from_table'] in facts:
                date_linked_facts.add(rel['from_table'])
            if rel['from_table'] in date_dimensions and rel['to_table'] in facts:
                date_linked_facts.add(rel['to_table'])

        return {
            "method": method,
            "roles": roles,
            "facts": facts,
            "dimensions": dimensions,
            "bridges": names_with_role('bridge'),
            "isolated": names_with_role('isolated'),
            "auto_date_tables": [t['name'] for t in tables if t['is_auto_date_table']],
            "date_dimensions": date_dimensions,
            "unconnected_date_tables": unconnected_date_tables,
            "has_date_dimension": bool(date_dimensions),
            "facts_without_date_link": [name for name in facts if name not in date_linked_facts],
            "relationship_count_by_table": {
                t['name']: len(acts_many.get(t['name'], [])) + len(acts_one.get(t['name'], []))
                for t in tables
            },
        }

    def _is_date_table_like(self, columns, data_category):
        """Tablo bir takvim/tarih boyutuna benziyor mu? (isimden değil içerikten)"""
        if (data_category or '').lower() == 'time':
            return True
        has_date_column = any(c['data_type'] in ('dateTime', 'date') for c in columns)
        if not has_date_column:
            return False
        part_columns = sum(1 for c in columns if is_dateish_name(c['name']))
        return part_columns >= 2

    # --------------------------------------------------------- report layout
    # Görsel/filtre tanımlarında alan referansları şu kalıplarda geçer:
    #   {"Column":  {"Expression": {"SourceRef": {"Source": "v"}}, "Property": "Kolon"}}
    #   {"Measure": {"Expression": {"SourceRef": {"Entity": "Tablo"}}, "Property": "Measure"}}
    #   {"Aggregation": {"Expression": {"Column": {...}}, "Function": 0}}
    #   {"HierarchyLevel": {"Expression": {"Hierarchy": {...}}, "Level": "Year"}}
    # "Source" bir takma addır; aynı sözlükteki "From" listesi onu tabloya çevirir.
    # Görselin "Name" alanı kullanıcının verdiği görünen ad olabilir (örn. "veri.Measure"),
    # bu yüzden alanın gerçek adı her zaman "Property"den okunur.

    DECORATIVE_VISUALS = {
        'textbox', 'image', 'shape', 'basicShape', 'actionButton',
        'pageNavigator', 'bookmarkNavigator',
    }
    SLICER_VISUALS = {'slicer', 'advancedSlicerVisual', 'listSlicer', 'textSlicer'}

    @staticmethod
    def _maybe_json(value):
        if isinstance(value, str) and value[:1] in ('{', '['):
            try:
                return json.loads(value)
            except (ValueError, TypeError):
                return None
        return None

    @classmethod
    def _entity_of(cls, expr, aliases):
        """Bir ifade ağacındaki ilk SourceRef'i tablo adına çevirir."""
        if isinstance(expr, dict):
            source_ref = expr.get('SourceRef')
            if isinstance(source_ref, dict):
                if 'Entity' in source_ref:
                    return source_ref['Entity']
                if 'Source' in source_ref:
                    return aliases.get(source_ref['Source'])
            for value in expr.values():
                found = cls._entity_of(value, aliases)
                if found:
                    return found
        elif isinstance(expr, list):
            for value in expr:
                found = cls._entity_of(value, aliases)
                if found:
                    return found
        return None

    @staticmethod
    def _with_aliases(node, aliases):
        from_list = node.get('From') if isinstance(node, dict) else None
        if not isinstance(from_list, list):
            return aliases
        scoped = dict(aliases)
        for item in from_list:
            if isinstance(item, dict) and 'Name' in item and 'Entity' in item:
                scoped[item['Name']] = item['Entity']
        return scoped

    def _resolve_field(self, node, aliases, hierarchy_levels):
        """Tek bir alan ifadesini (tablo, alan, tür, aggregation) olarak çözer."""
        if not isinstance(node, dict):
            return None
        if isinstance(node.get('Measure'), dict):
            m = node['Measure']
            return {"table": self._entity_of(m.get('Expression'), aliases), "field": m.get('Property'),
                    "kind": "measure", "agg": None}
        if isinstance(node.get('Column'), dict):
            c = node['Column']
            return {"table": self._entity_of(c.get('Expression'), aliases), "field": c.get('Property'),
                    "kind": "column", "agg": None}
        if isinstance(node.get('Aggregation'), dict):
            inner = self._resolve_field(node['Aggregation'].get('Expression', {}), aliases, hierarchy_levels)
            if inner:
                inner = dict(inner)
                inner['agg'] = node['Aggregation'].get('Function')
                inner['kind'] = 'aggregation'
            return inner
        if isinstance(node.get('HierarchyLevel'), dict):
            hl = node['HierarchyLevel']
            hierarchy = (hl.get('Expression') or {}).get('Hierarchy') or {}
            level = hl.get('Level')
            expr = hierarchy.get('Expression') or {}
            variation = expr.get('PropertyVariationSource')
            if isinstance(variation, dict):
                # Otomatik tarih hiyerarşisi: asıl kolon variation'ın Property'si
                table = self._entity_of(variation.get('Expression'), aliases)
                return {"table": table, "field": variation.get('Property'), "kind": "column",
                        "agg": None, "date_hierarchy_level": level}
            table = self._entity_of(expr, aliases)
            column = hierarchy_levels.get((table, hierarchy.get('Hierarchy'), level), level)
            return {"table": table, "field": column, "kind": "column", "agg": None,
                    "hierarchy": hierarchy.get('Hierarchy'), "hierarchy_level": level}
        return None

    def _collect_refs(self, node, aliases, hierarchy_levels, out):
        """Herhangi bir JSON ağacında geçen tüm alan referanslarını toplar."""
        parsed = self._maybe_json(node)
        if parsed is not None:
            node = parsed
        if isinstance(node, dict):
            aliases = self._with_aliases(node, aliases)
            if any(key in node for key in ('Measure', 'Column', 'HierarchyLevel')):
                field = self._resolve_field(node, aliases, hierarchy_levels)
                if field and field.get('table') and field.get('field'):
                    out.add((field['table'], field['field'], 'measure' if field['kind'] == 'measure' else 'column'))
            for value in node.values():
                self._collect_refs(value, aliases, hierarchy_levels, out)
        elif isinstance(node, list):
            for value in node:
                self._collect_refs(value, aliases, hierarchy_levels, out)

    def _visual_fields(self, single_visual, hierarchy_levels):
        """Görselin alanlarını rolleriyle birlikte döndürür (Category, Y, Values, ...)."""
        query = single_visual.get('prototypeQuery') or {}
        aliases = self._with_aliases(query, {})
        by_ref = {}
        for item in query.get('Select', []) or []:
            if not isinstance(item, dict):
                continue
            field = self._resolve_field(item, aliases, hierarchy_levels)
            if field:
                field['display_name'] = item.get('NativeReferenceName')
                by_ref[item.get('Name')] = field

        fields = []
        seen = set()
        for role, entries in (single_visual.get('projections') or {}).items():
            for entry in entries or []:
                ref = entry.get('queryRef') if isinstance(entry, dict) else None
                if ref in by_ref:
                    field = dict(by_ref[ref])
                    field['role'] = role
                    fields.append(field)
                    seen.add(ref)
        # Projeksiyonda olmayan ama sorguda olan alanlar (eski formatlar)
        for ref, field in by_ref.items():
            if ref not in seen:
                field = dict(field)
                field['role'] = None
                fields.append(field)
        return fields

    @staticmethod
    def _visual_title(cfg):
        title_objects = (cfg.get('vcObjects') or {}).get('title', [])
        if not title_objects:
            return None
        expr = (title_objects[0].get('properties') or {}).get('text', {}).get('expr', {})
        if isinstance(expr, dict):
            value = (expr.get('Literal') or {}).get('Value')
            if isinstance(value, str) and len(value) >= 2 and value[0] == value[-1] == "'":
                return value[1:-1]
            return value
        return None

    def _parse_report_layout(self, zip_file, model, hierarchy_levels):
        empty = {
            "page_count": 0, "visual_count": 0, "data_visual_count": 0, "pages": [],
            "visual_type_counts": {}, "field_refs": [], "visuals": [],
            "used_measure_names": [], "used_column_names": [],
        }
        try:
            report = self._decode_json_from_zip(zip_file, 'Report/Layout')
        except Exception:
            return empty

        refs = set()
        # Rapor ve sayfa düzeyindeki filtreler / ayarlar
        for key in ('filters', 'config'):
            self._collect_refs(report.get(key), {}, hierarchy_levels, refs)

        visual_type_counts = Counter()
        pages = []
        visuals = []

        for section in report.get('sections', []) or []:
            page_name = section.get('displayName') or section.get('name') or "Sayfa"
            for key in ('filters', 'config'):
                self._collect_refs(section.get(key), {}, hierarchy_levels, refs)

            page_visuals = []
            page_type_counts = Counter()
            for vc in section.get('visualContainers', []) or []:
                # Görselin tüm parçalarındaki (config, filters, query, dataTransforms) referanslar
                for key in ('config', 'filters', 'query', 'dataTransforms'):
                    self._collect_refs(vc.get(key), {}, hierarchy_levels, refs)

                cfg = self._maybe_json(vc.get('config')) or {}
                single_visual = cfg.get('singleVisual')
                if not isinstance(single_visual, dict):
                    continue  # görsel grubu vb.
                visual_type = single_visual.get('visualType', 'unknown')
                visual_type_counts[visual_type] += 1
                page_type_counts[visual_type] += 1

                fields = self._visual_fields(single_visual, hierarchy_levels)
                visual_info = {
                    "page": page_name,
                    "type": visual_type,
                    "title": self._visual_title(cfg),
                    "is_decorative": visual_type in self.DECORATIVE_VISUALS,
                    "is_slicer": visual_type in self.SLICER_VISUALS,
                    "fields": fields,
                    # Geriye dönük uyumluluk
                    "measure_names": [f['field'] for f in fields if f['kind'] == 'measure'],
                    "column_names": [f['field'] for f in fields if f['kind'] != 'measure'],
                }
                page_visuals.append(visual_info)
                visuals.append(visual_info)

            data_visuals = [v for v in page_visuals if not v['is_decorative'] and not v['is_slicer']]
            pages.append({
                "name": page_name,
                "visual_count": len(page_visuals),
                "data_visual_count": len(data_visuals),
                "slicer_count": sum(1 for v in page_visuals if v['is_slicer']),
                "visual_types": dict(page_type_counts),
                "visuals": page_visuals,
            })

        return {
            "page_count": len(pages),
            "visual_count": len(visuals),
            "data_visual_count": sum(p['data_visual_count'] for p in pages),
            "pages": pages,
            "visual_type_counts": dict(visual_type_counts),
            "field_refs": sorted(refs),
            "visuals": visuals,
            "used_measure_names": sorted({f for t, f, k in refs if k == 'measure'}),
            "used_column_names": sorted({f for t, f, k in refs if k == 'column'}),
        }

    # ------------------------------------------------------------------ api
    def get_clean_data(self):
        try:
            with zipfile.ZipFile(self.file_path, 'r') as z:
                data = self._decode_json_from_zip(z, 'DataModelSchema')
                model = data.get('model', {})
                tables = []
                measures_list = []
                hierarchy_levels = {}

                for t in model.get('tables', []):
                    cols = [self._parse_column(c) for c in t.get('columns', []) or []]
                    measures = [self._parse_measure(m, t['name']) for m in t.get('measures', []) or []]
                    measures_list.extend(measures)

                    partitions = self._parse_partitions(t)
                    primary_query = partitions[0]['expression'] if partitions else ""

                    hierarchies = []
                    for h in t.get('hierarchies', []) or []:
                        levels = [lv.get('column') for lv in h.get('levels', []) or []]
                        hierarchies.append({"name": h.get('name'), "levels": levels})
                        for lv in h.get('levels', []) or []:
                            hierarchy_levels[(t['name'], h.get('name'), lv.get('name'))] = lv.get('column')

                    tables.append({
                        "name": t['name'],
                        "hierarchies": hierarchies,
                        "cols": cols,
                        "measures": measures,
                        # Eski anahtar adı korunuyor ama artık gerçekten kolon sayısı
                        "row_count": len(cols),
                        "col_count": len(cols),
                        # Eski davranışta query 500 karakterde kesiliyordu; analizin
                        # SELECT * / NOLOCK taramasını bozmamak için tamamını tutuyoruz.
                        "query": primary_query,
                        "partitions": partitions,
                        "partition_mode": partitions[0]['mode'] if partitions else None,
                        "partition_source_type": partitions[0]['source_type'] if partitions else None,
                        "is_hidden": t.get('isHidden', False),
                        "is_private": t.get('isPrivate', False),
                        "data_category": t.get('dataCategory'),
                        "is_auto_date_table": self._is_auto_date_table(t, partitions),
                        "is_date_table_like": self._is_date_table_like(cols, t.get('dataCategory')),
                        "calculated_columns": [c['name'] for c in cols if c['is_calculated']],
                        "date_columns": [c['name'] for c in cols if c['data_type'] in ('dateTime', 'date')],
                    })

                auto_tables = {t['name'] for t in tables if t['is_auto_date_table']}
                relationships = []
                for raw_rel in model.get('relationships', []) or []:
                    rel = self._parse_relationship(raw_rel)
                    # Auto date/time'ın gizli tarih tablolarına kurduğu ilişkiler kullanıcı modeline ait değil
                    rel['involves_auto_date'] = rel['from_table'] in auto_tables or rel['to_table'] in auto_tables
                    relationships.append(rel)
                model_relationships = [r for r in relationships if not r['involves_auto_date']]
                profile = self._build_profile(tables, model_relationships)
                report_layout = self._parse_report_layout(z, model, hierarchy_levels)

                roles = []
                for role in model.get('roles', []) or []:
                    filters = []
                    for perm in role.get('tablePermissions', []) or []:
                        expression = normalize_expression(perm.get('filterExpression'))
                        if expression:
                            filters.append({"table": perm.get('name'), "expression": expression})
                    roles.append({"name": role.get('name'), "filters": filters})

                visible_tables = [t for t in tables if not t['is_auto_date_table']]

                return {
                    "tables": tables,
                    "visible_tables": visible_tables,
                    "rels": model_relationships,
                    "all_rels": relationships,
                    "roles": roles,
                    "measures": measures_list,
                    "table_count": len(tables),
                    "visible_table_count": len(visible_tables),
                    "rel_count": len(model_relationships),
                    "measure_count": len(measures_list),
                    "column_count": sum(len(t['cols']) for t in tables),
                    "culture": model.get('culture'),
                    "profile": profile,
                    "report_layout": report_layout,
                }
        except Exception as e:
            return f"Error reading PBIT: {e}"
