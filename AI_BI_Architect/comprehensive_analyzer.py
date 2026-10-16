#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Power BI (.pbit) kapsamlı denetim motoru.

Puanlama (findings.SCORE_MODEL):
  Veri Modellemesi (40)        : Star schema 10, N-N 8, Çift yönlü 8, Kardinalite/aktif-pasif 6,
                                 İlişkisiz tablo 4, Calendar dimension 4
  Sorgu + DAX + Veri Tipi (30) : SQL 8, Veri tipi + kullanılmayan kolon 12, DAX 10
                                 (uygulanamayan bölümün puanı diğerlerine orantılı dağıtılır)
  Görselleştirme (30)          : Görsel yoğunluğu 12, Grafik uygunluğu 10, İsimlendirme 8

Her kova kendi puanıyla başlar, bulguların kesintisi kadar düşer. Puan kırmayan
gözlemler "bilgi notu" olarak raporda yer alır.

Akış: parser -> kural analizleri -> puan -> (opsiyonel) AI yorumu -> konsol/HTML/JSON
"""

import argparse
import json
import re
import sys
import textwrap
from collections import Counter, defaultdict
from datetime import datetime
from pathlib import Path

from agents import DEFAULT_MODEL, BIAgents
from findings import (
    BUCKET_INFO, CATEGORY_LABELS, CATEGORY_MAX, PENALTY_SCALE, Finding, capped_penalty, compute_breakdown,
    effective_weights, penalty_factor, sort_findings,
)
from naming import REASON_LABELS, evaluate_naming
from pbit_parser import NUMERIC_TYPES, PBITParser, fold_name, is_date_value_name, is_dateish_name, looks_numeric_name
from report_html import build_html_report
from usage import UsageAnalysis, strip_dax
from visual_rules import evaluate_report

DENSITY_LIMIT = 7  # sayfa başına en fazla veri görseli (slicer, metin kutusu, şekil, resim, buton hariç)

ITERATOR_FUNCTIONS = (
    'sumx', 'averagex', 'minx', 'maxx', 'countx', 'countax', 'rankx', 'concatenatex',
    'productx', 'generate', 'addcolumns', 'topn', 'selectcolumns',
)
EXCEL_ONLY_FUNCTIONS = ('countif', 'countifs', 'sumif', 'sumifs', 'averageif', 'sumproduct', 'vlookup', 'hlookup')
NATIVE_QUERY_MARKERS = ('odbc.query(', 'value.nativequery(', 'query="', 'query = "', '[query=')
DB_CONNECTORS = (
    'sql.database', 'odbc.datasource', 'odbc.query', 'oracle.database', 'postgresql.database',
    'mysql.database', 'teradata.database', 'snowflake.databases', 'googlebigquery.database',
    'amazonredshift.database', 'saphana.database', 'db2.database', 'sybase.database',
    'informix.database', 'oledb.datasource',
)
ID_LIKE_TOKENS = ('id', 'kod', 'code', 'no', 'year', 'yil', 'month', 'ay', 'numara', 'number')

# SQL: FROM/JOIN ile okunan tablo + opsiyonel takma ad + opsiyonel tablo ipucu
_SQL_KEYWORDS = r'(?:with|where|join|inner|left|right|full|cross|outer|on|group|order|union|having|option|pivot|unpivot|apply)'
FROM_JOIN = re.compile(
    r"\b(from|join)\s+"
    r"((?:\[[^\]]+\]|[A-Za-z_#@][\w#@$]*)(?:\s*\.\s*(?:\[[^\]]+\]|[A-Za-z_#@][\w#@$]*))*)"
    r"(\s+(?:as\s+)?(?!" + _SQL_KEYWORDS + r"\b)[A-Za-z_]\w*)?"
    r"(\s*(?:with\s*)?\(\s*(?:nolock|readuncommitted)[^)]*\))?",
    re.IGNORECASE,
)
CTE_NAME = re.compile(r"(?:\bwith\s+|,\s*)([A-Za-z_]\w*)\s+as\s*\(", re.IGNORECASE)
NON_SARGABLE = re.compile(
    r"\b(year|month|day|datepart|datename|convert|cast|isnull|coalesce|upper|lower|ltrim|rtrim|trim|"
    r"substring|left|right|format|strftime|datediff|dateadd|eomonth|replace|len)\s*\([^()]*\)\s*"
    r"(=|<>|!=|<=|>=|<|>|\blike\b|\bin\b|\bbetween\b)",
    re.IGNORECASE,
)
WHERE_CLAUSE = re.compile(
    r"\bwhere\b(.*?)(?=\bgroup\s+by\b|\border\s+by\b|\bhaving\b|\bunion\b|\)\s*select\b|$)",
    re.IGNORECASE | re.DOTALL,
)


class ComprehensiveAnalyzer:
    def __init__(self, pbit_file, model_name=DEFAULT_MODEL, use_ai=True, verbose=True, display_name=None):
        self.pbit_file = pbit_file
        # Raporda görünen ad (web arayüzünde geçici dosya yolu yerine orijinal dosya adı)
        self.display_name = display_name or Path(pbit_file).name
        self.verbose = verbose
        self.parser = PBITParser(pbit_file)
        self.metadata = self.parser.get_clean_data()
        self.use_ai = use_ai
        self.ai = BIAgents(model_name=model_name) if use_ai else None
        self.category_max = dict(CATEGORY_MAX)
        self.findings = []
        self.breakdown = {}
        self.scores = {}
        self.visual_reviews = []
        self.usage = None
        self.applicability = {}
        self.scope_notes = {}
        self.weights = effective_weights({})
        self.ai_commentary = None
        self.ai_note = None
        self.ai_warnings = []

    # ================================================================ yardımcılar
    @property
    def ok(self):
        return not isinstance(self.metadata, str)

    @property
    def profile(self):
        return self.metadata.get('profile', {}) if self.ok else {}

    @property
    def visible_tables(self):
        return self.metadata.get('visible_tables', []) if self.ok else []

    def _log(self, *args):
        if self.verbose:
            print(*args)

    def _factor(self, bucket):
        return penalty_factor(bucket, self.weights)

    def _score(self, bucket, severity, title, detail="", evidence=None, fix="", penalty=0.0):
        """Puan kıran bulgu ekler (kova -> kategori otomatik).

        penalty, kuralın PENALTY_SCALE ölçeğindeki kesintisidir; burada kovanın geçerli
        ağırlığına çevrilir, böylece raporda gösterilen kesinti gerçek puan kaybıdır.
        """
        category, label, _ = BUCKET_INFO[bucket]
        penalty = round(penalty * self._factor(bucket), 2)
        finding = Finding(category, label, severity, title, detail, list(evidence or []), fix, penalty, bucket)
        self.findings.append(finding)
        return finding

    def _note(self, category, area, title, detail="", evidence=None, fix=""):
        """Puan kırmayan bilgi notu ekler."""
        finding = Finding(category, area, 'info', title, detail, list(evidence or []), fix, 0.0, None)
        self.findings.append(finding)
        return finding

    def _section(self, title, findings):
        self._log("\n" + "=" * 80)
        self._log(title)
        self._log("=" * 80)
        if not findings:
            self._log("   ✅ Belirgin bir sorun bulunmadı")
            return
        for finding in sort_findings(findings):
            penalty = f"  (-{finding.penalty:g})" if finding.penalty else ""
            self._log(f"   {finding.icon} [{finding.severity_label}] {finding.title}{penalty}")
            if finding.detail:
                self._log(f"      {finding.detail}")
            if finding.evidence:
                sample = ', '.join(str(e) for e in finding.evidence[:6])
                more = f" (+{len(finding.evidence) - 6})" if len(finding.evidence) > 6 else ""
                self._log(f"      ↳ {sample}{more}")
            if finding.fix:
                self._log(f"      💡 {finding.fix}")

    def _run_section(self, title, method):
        before = len(self.findings)
        method()
        self._section(title, self.findings[before:])

    @staticmethod
    def _draw_score_bar(score, max_score, width=32):
        if max_score <= 0:
            return "[n/a]"
        percentage = max(0, min(100, (score / max_score) * 100))
        filled = int((percentage / 100) * width)
        bar = "█" * filled + "░" * (width - filled)
        color = "🟢" if percentage >= 80 else ("🟡" if percentage >= 60 else "🔴")
        return f"{color} [{bar}] {score:5.1f}/{max_score:g}"

    @staticmethod
    def _box(title, lines, width=78):
        inner_width = width - 4
        top = f"┏{'━' * (width - 2)}┓"
        title_line = f"┃ {title[:inner_width].ljust(inner_width)} ┃"
        separator = f"┣{'━' * (width - 2)}┫"
        body = []
        for line in (lines or [""]):
            for chunk in textwrap.wrap(str(line), inner_width, subsequent_indent="          ") or [""]:
                body.append(f"┃ {chunk.ljust(inner_width)} ┃")
        bottom = f"┗{'━' * (width - 2)}┛"
        return "\n".join([top, title_line, separator, *body, bottom])

    @staticmethod
    def _status_for_score(total_score):
        if total_score >= 85:
            return "🟢 ÜST DÜZEY", "Rapor üretim ortamına hazır"
        if total_score >= 70:
            return "🟡 İYİ", "Bazı iyileştirmeler gerekli"
        if total_score >= 50:
            return "🟠 ORTA", "Önemli düzeltmeler gerekli"
        return "🔴 KRİTİK", "Acil müdahale gerekli"

    @staticmethod
    def _rel_label(rel):
        return f"{rel['from_table']}[{rel['from_col']}] → {rel['to_table']}[{rel['to_col']}]"

    def _referenced_model_tables(self, query_text):
        """Bir kaynak sorgunun FROM/JOIN ile modeldeki hangi tabloları okuduğunu bulur."""
        names = {fold_name(t['name']): t['name'] for t in self.visible_tables}
        referenced = set()
        for match in re.finditer(r'\b(?:from|join)\s+[\[\"`]?([\w\.]+)', query_text, flags=re.IGNORECASE):
            key = fold_name(match.group(1).split('.')[-1])
            if key in names:
                referenced.add(names[key])
        return referenced

    def _structure(self):
        """İlişki yönlerinden yıldız şema yapısını çıkarır.

        many_links[t]: t'nin 'çok' tarafında olduğu ilişkiler (t -> dimension)
        one_links[t] : t'nin 'bir' tarafında olduğu ilişkiler (fact -> t)
        fact_like    : en az 2 dimension'a bağlanan ya da sadece 'çok' tarafında duran tablolar
        """
        visible = {t['name'] for t in self.visible_tables}
        many_links, one_links = defaultdict(list), defaultdict(list)
        for rel in self.metadata.get('rels', []):
            if rel['is_many_to_many'] or rel['is_one_to_one']:
                continue
            if rel['from_cardinality'] == 'many':
                many_side, one_side = rel['from_table'], rel['to_table']
            else:
                many_side, one_side = rel['to_table'], rel['from_table']
            many_links[many_side].append((one_side, rel))
            one_links[one_side].append((many_side, rel))
        fact_like = {
            t for t in visible
            if len(many_links[t]) >= 2 or (many_links[t] and not one_links[t])
        }
        return many_links, one_links, fact_like

    # ======================================================== 1. VERİ MODELLEMESİ
    def analyze_star_schema(self):
        tables = self.visible_tables
        many_links, one_links, fact_like = self._structure()

        if len(tables) > 1 and not fact_like:
            self._score('star_schema', 'critical', "Modelde fact tablosu tespit edilemedi",
                        detail="Hiçbir tablo dimension'lara bağlanan merkez tablo konumunda değil; "
                               "star schema kurulmamış.",
                        fix="Ölçülebilir olayları (satış, şikayet…) tutan bir fact tablosu oluştur ve "
                            "dimension'ları ona 1-N ilişkiyle bağla.",
                        penalty=6)

        fact_to_fact = []
        snowflake = []
        for many_side, links in many_links.items():
            for one_side, rel in links:
                if one_side in fact_like:
                    fact_to_fact.append(self._rel_label(rel))
                elif many_side not in fact_like:
                    snowflake.append(self._rel_label(rel))
        if fact_to_fact:
            self._score('star_schema', 'high', "Fact-to-fact ilişki",
                        detail="Bir fact tablosu doğrudan başka bir fact'e bağlı. Filtreler fact'ler arasında "
                               "beklenmedik şekilde yayılır ve toplamlar yanlış çıkabilir.",
                        evidence=fact_to_fact,
                        fix="İki fact'i ortak (conformed) dimension'lar üzerinden ilişkilendir.",
                        penalty=capped_penalty(4, len(fact_to_fact), 8))
        if snowflake:
            self._score('star_schema', 'medium', "Dimension'dan dimension'a ilişki (snowflake)",
                        detail="Dimension'lar fact'e doğrudan değil, başka bir dimension üzerinden bağlanıyor.",
                        evidence=snowflake,
                        fix="Zincirdeki dimension'ları birleştir (denormalize et) ve fact'e doğrudan bağla.",
                        penalty=capped_penalty(2, len(snowflake), 6))

        weak_facts = []
        for fact in sorted(fact_like):
            dims = sorted({one for one, _ in many_links[fact] if one not in fact_like})
            if len(dims) < 2:
                weak_facts.append(f"{fact} ({len(dims)} dimension{': ' + ', '.join(dims) if dims else ''})")
        if weak_facts:
            self._score('star_schema', 'medium', "Birden fazla dimension'a bağlanmayan fact tablosu",
                        detail="Star schema'da fact tablosu analiz eksenlerini (tarih, müşteri, ürün…) "
                               "dimension'lardan alır; tek dimension'lı fact yapının eksik olduğunu gösterir.",
                        evidence=weak_facts,
                        fix="Fact'teki kategorik/tarih kolonları için dimension tabloları oluştur ve fact'e bağla.",
                        penalty=capped_penalty(3, len(weak_facts), 6))

        pre_aggregated = []
        for table in tables:
            query = (table.get('query') or '').lower()
            if 'group by' not in query and 'row_number' not in query:
                continue
            sources = self._referenced_model_tables(query) - {table['name']}
            if sources:
                pre_aggregated.append(f"{table['name']} ← {', '.join(sorted(sources))}")
        if pre_aggregated:
            self._score('star_schema', 'high', f"Modeldeki bir tablodan türetilmiş {len(pre_aggregated)} ön-toplanmış tablo",
                        detail="Aynı veri hem detay hem toplanmış halde yükleniyor. Her soru için ayrı tablo "
                               "modeli şişirir ve slicer'ların bu tablolara etki etmesini engeller.",
                        evidence=pre_aggregated,
                        fix="Bu tabloları kaldırıp hesapları fact tablosu üzerinde measure olarak yaz.",
                        penalty=capped_penalty(1.5, len(pre_aggregated), 6))

    def analyze_relationships(self):
        rels = self.metadata.get('rels', [])
        _, _, fact_like = self._structure()

        many_to_many = []
        for rel in rels:
            if rel['is_many_to_many']:
                label = self._rel_label(rel)
                if rel['from_table'] in fact_like and rel['to_table'] in fact_like:
                    label += " (fact-to-fact)"
                many_to_many.append(label)
        if many_to_many:
            self._score('many_to_many', 'high', f"{len(many_to_many)} many-to-many (N-N) ilişki",
                        detail="N-N ilişkiler belirsiz filtre yayılımı ve yavaş sorgular üretir. "
                               "Gerçekten zorunluysa bu bulgu göz ardı edilebilir.",
                        evidence=many_to_many,
                        fix="Araya benzersiz anahtarlı bir bridge tablo koyup iki adet 1-N ilişki kur.",
                        penalty=capped_penalty(4, len(many_to_many), 8))

        bidirectional = [self._rel_label(r) for r in rels if r['is_bidirectional']]
        if bidirectional:
            self._score('bidirectional', 'high', f"{len(bidirectional)} çift yönlü (bi-directional) filtre",
                        detail="Çift yönlü filtreler belirsiz filtre yolları oluşturabilir ve sorgu maliyetini artırır.",
                        evidence=bidirectional,
                        fix="Filtre yönünü 'Single' yap; gereken tek hesapta CROSSFILTER(..., BOTH) kullan.",
                        penalty=capped_penalty(4, len(bidirectional), 8))

        one_to_one = [self._rel_label(r) for r in rels if r['is_one_to_one']]
        if one_to_one:
            self._score('relationship_design', 'medium', "1-1 ilişki",
                        detail="1-1 ilişki genellikle iki tablonun tek tabloda birleştirilmesi gerektiğini gösterir.",
                        evidence=one_to_one,
                        fix="Tabloları Power Query'de birleştir (Merge) ve ilişkiyi kaldır.",
                        penalty=capped_penalty(2, len(one_to_one), 4))

        inactive = [self._rel_label(r) for r in rels if not r['is_active']]
        if inactive:
            dax_text = ' '.join(m['formula_full'].lower() for m in self.metadata.get('measures', []))
            if 'userelationship' in dax_text:
                self._note('modeling', 'Kardinalite ve aktif/pasif', "Pasif ilişkiler USERELATIONSHIP ile kullanılıyor",
                           evidence=inactive)
            else:
                self._score('relationship_design', 'medium', "Hiçbir measure'ın kullanmadığı pasif ilişki",
                            detail="Pasif ilişki yalnızca USERELATIONSHIP ile devreye girer; kullanılmıyorsa ölü yapıdır.",
                            evidence=inactive,
                            fix="Rol oynayan tarih için USERELATIONSHIP içeren measure yaz ya da ilişkiyi kaldır.",
                            penalty=capped_penalty(2, len(inactive), 4))

        col_types = {(t['name'], c['name']): c['data_type'] for t in self.metadata['tables'] for c in t['cols']}
        string_keys = [
            self._rel_label(r) for r in rels
            if 'string' in (col_types.get((r['from_table'], r['from_col'])), col_types.get((r['to_table'], r['to_col'])))
        ]
        if string_keys:
            self._score('relationship_design', 'medium', "İlişki anahtarı metin (string) tipinde",
                        detail="Metin anahtarlar daha büyük sözlük ve daha yavaş join üretir.",
                        evidence=string_keys,
                        fix="Anahtar kolonları kaynakta tamsayıya (int64) çevir veya surrogate key üret.",
                        penalty=capped_penalty(1, len(string_keys), 3))

        isolated = self.profile.get('isolated', [])
        if isolated and len(self.visible_tables) > 1:
            self._score('isolated', 'high', f"Hiçbir ilişkisi olmayan {len(isolated)} tablo",
                        detail="İlişkisiz tablolar diğer tablolardaki slicer/filtrelerden etkilenmez; "
                               "raporda tutarsız sonuçlara yol açar.",
                        evidence=isolated,
                        fix="Tabloyu bir dimension'a bağla ya da measure ile çözülebiliyorsa modelden kaldır.",
                        penalty=capped_penalty(2, len(isolated), 5))
            self._suggest_relationships(isolated)

        date_dims = self.profile.get('date_dimensions', [])
        if not date_dims:
            detail = "Fact tablolarını zaman ekseninde filtreleyecek, ilişkili bir tarih tablosu yok."
            if self.profile.get('auto_date_tables'):
                detail += " Otomatik (gizli) tarih tabloları merkezi bir dimension yerine geçmez."
            self._score('calendar', 'critical', "Merkezi Calendar/Date dimension yok",
                        detail=detail,
                        evidence=self.profile.get('unconnected_date_tables', []),
                        fix="CALENDARAUTO() veya Power Query ile Tarih tablosu oluştur, 'Mark as date table' ile "
                            "işaretle ve fact'lerin tarih kolonlarını bu tabloya bağla.",
                        penalty=4)
        else:
            linked = set()
            for rel in rels:
                if rel['to_table'] in date_dims:
                    linked.add(rel['from_table'])
                if rel['from_table'] in date_dims:
                    linked.add(rel['to_table'])
            unlinked = sorted(f for f in fact_like if f not in linked and f not in date_dims)
            if unlinked:
                self._score('calendar', 'high', "Tarih dimension'ına bağlı olmayan fact tablosu",
                            evidence=unlinked,
                            fix="Fact'in tarih kolonunu merkezi tarih tablosuna bağla.",
                            penalty=capped_penalty(2, len(unlinked), 4))

    def _suggest_relationships(self, isolated):
        roles = self.profile.get('roles', {})
        connected = [t for t in self.visible_tables if roles.get(t['name']) not in ('isolated', 'auto_date')]
        suggestions = []
        for table in self.visible_tables:
            if table['name'] not in isolated:
                continue
            for col in table['cols']:
                key = fold_name(col['name'])
                if len(key) < 4:
                    continue
                for target in connected:
                    for target_col in target['cols']:
                        if fold_name(target_col['name']) == key:
                            suggestions.append(f"{table['name']}[{col['name']}] ↔ {target['name']}[{target_col['name']}]")
        if suggestions:
            self._note('modeling', 'İlişkisiz tablolar', f"İlişkisiz tablolar için {len(suggestions)} olası ilişki adayı",
                       detail="Kolon adları (Türkçe karakter ve boşluk normalize edilerek) eşleşiyor.",
                       evidence=suggestions,
                       fix="Kardinaliteyi doğrula; anahtar dimension tarafında benzersizse 1-N ilişki kur.")

    # ============================================================== 2. SQL
    @staticmethod
    def _is_native_sql(lower_query):
        return any(marker in lower_query for marker in NATIVE_QUERY_MARKERS) and 'select' in lower_query

    def _missing_nolock(self, sql):
        if re.search(r'set\s+transaction\s+isolation\s+level\s+read\s+uncommitted', sql, re.IGNORECASE):
            return []
        ctes = {m.group(1).lower() for m in CTE_NAME.finditer(sql)}
        missing = []
        for match in FROM_JOIN.finditer(sql):
            table = re.sub(r'\s+', '', match.group(2))
            if table.startswith(('@', '#')) or table.lower().strip('[]') in ctes:
                continue
            if not match.group(4):
                missing.append(table)
        return missing

    def analyze_sql(self):
        select_star, full_load, nolock, order_by = [], [], [], []
        non_sargable, wildcard, union, native, hardcoded, nav_sql_server = [], [], [], [], [], []

        for table in self.visible_tables:
            if table.get('partition_source_type') != 'm':
                continue
            query = table.get('query') or ''
            lower = query.lower()
            name = table['name']
            is_sql_server = 'sql.database(' in lower or 'sql.databases(' in lower
            is_db = any(conn in lower for conn in DB_CONNECTORS)

            if self._is_native_sql(lower):
                native.append(name)
                if re.search(r'\bselect\s+(?:distinct\s+)?(?:top\s*\(?\s*\d+\s*\)?\s+)?(?:\w+\.)?\*', lower):
                    select_star.append(name)
                if is_sql_server:
                    missing = self._missing_nolock(query)
                    if missing:
                        nolock.append(f"{name}: {', '.join(sorted(set(missing)))}")
                without_windows = re.sub(r'over\s*\((?:[^()]|\([^()]*\))*\)', '', lower)
                if re.search(r'\border\s+by\b', without_windows) and not re.search(r'\btop\s*\(?\s*\d|\boffset\b', lower):
                    order_by.append(name)
                for clause in WHERE_CLAUSE.findall(query):
                    match = NON_SARGABLE.search(clause)
                    if match:
                        non_sargable.append(f"{name}: {match.group(0).strip()[:60]}")
                        break
                if re.search(r"\blike\s+n?'%", lower):
                    wildcard.append(name)
                if re.search(r'\bunion\b(?!\s+all\b)', lower):
                    union.append(name)
                if re.search(r"\bwhere\b[^;]*?=\s*'[^']*'", lower):
                    hardcoded.append(name)
            elif is_db:
                navigation = re.search(r'\{\s*\[.*?\]\s*\}\s*\[\s*data\s*\]', lower, re.DOTALL)
                selects = any(fn in lower for fn in ('table.selectcolumns', 'table.removecolumns', 'table.removeothercolumns'))
                if navigation and not selects:
                    full_load.append(name)
                if is_sql_server:
                    nav_sql_server.append(name)

        if select_star:
            self._score('sql', 'high', "SELECT * kullanımı",
                        detail="Kullanılmayan kolonlar da yüklenir; kaynakta şema değişince refresh kırılır.",
                        evidence=select_star,
                        fix="Sadece raporda kullanılan kolonları SELECT listesinde açıkça yaz.",
                        penalty=capped_penalty(3, len(select_star), 9))
        if full_load:
            self._score('sql', 'medium', "Tablonun tüm kolonları yükleniyor (SELECT * eşdeğeri)",
                        detail="Tablo, kolon seçimi yapılmadan doğrudan veritabanından okunuyor.",
                        evidence=full_load,
                        fix="Kolonları SQL sorgusunda açıkça seç ya da Power Query'de 'Choose Columns' "
                            "(Table.SelectColumns) adımı ekle.",
                        penalty=capped_penalty(1.5, len(full_load), 6))
        if nolock:
            self._score('sql', 'high', "WITH (NOLOCK) kullanılmayan SQL Server sorguları",
                        detail="Standarda göre raporlama sorguları kaynak tabloları kilitlememek için NOLOCK ile "
                               "okunmalı. Listede NOLOCK eksik olan tablolar var.",
                        evidence=nolock,
                        fix="Her FROM/JOIN tablosunun arkasına WITH (NOLOCK) ekle "
                            "(örn. FROM dbo.Satis s WITH (NOLOCK)).",
                        penalty=capped_penalty(2, len(nolock), 8))
        if non_sargable:
            self._score('sql', 'medium', "WHERE koşulunda kolona fonksiyon uygulanıyor",
                        detail="Kolon bir fonksiyonun içine alındığında veritabanı indeksi kullanamaz ve tabloyu baştan "
                               "sona tarar.",
                        evidence=non_sargable,
                        fix="Koşulu kolonu çıplak bırakacak şekilde yaz: YEAR(Tarih) = 2024 yerine "
                            "Tarih >= '2024-01-01' AND Tarih < '2025-01-01'.",
                        penalty=capped_penalty(1, len(non_sargable), 4))
        if order_by:
            self._score('sql', 'low', "Kaynak sorguda gereksiz ORDER BY",
                        detail="Import sırasında satır sırası korunmaz; ORDER BY sadece sorguyu yavaşlatır.",
                        evidence=order_by,
                        fix="ORDER BY'ı kaldır; sıralamayı görselde veya 'Sort by column' ile yap.",
                        penalty=capped_penalty(1, len(order_by), 4))
        if wildcard:
            self._score('sql', 'medium', "Başında joker karakter olan LIKE ('%…')",
                        detail="LIKE '%değer' indeks kullanamaz ve tam tablo taraması yapar.",
                        evidence=wildcard,
                        fix="Mümkünse LIKE 'değer%' kullan veya aramayı tam eşitliğe çevir.",
                        penalty=capped_penalty(1, len(wildcard), 2))
        if union:
            self._score('sql', 'low', "UNION ALL yerine UNION",
                        detail="UNION, tekrarlı satırları elemek için ek sıralama yapar.",
                        evidence=union,
                        fix="Tekrar riski yoksa UNION ALL kullan.",
                        penalty=capped_penalty(0.5, len(union), 1))

        if native:
            self._note('query', 'SQL sorguları', f"{len(native)} tablo native SQL ile yükleniyor",
                       detail="Native sorgudan sonraki Power Query adımları kaynağa katlanamaz (query folding).",
                       evidence=native,
                       fix="Ek Power Query dönüşümü gerekiyorsa mantığı SQL'e veya veritabanı view'ına taşı.")
        if hardcoded:
            self._note('query', 'SQL sorguları', "Sorguda sabit filtre değeri",
                       detail="Filtre kaynakta sabitlenince kullanıcı slicer ile değiştiremez.",
                       evidence=hardcoded,
                       fix="Filtreyi slicer/measure ile uygula ya da Power Query parametresine çevir.")
        if nav_sql_server:
            self._note('query', 'SQL sorguları', "NOLOCK uygulanamayan SQL Server tabloları",
                       detail="Bu tablolar SQL yazılmadan (navigation) okunuyor; NOLOCK ipucu eklenemez.",
                       evidence=nav_sql_server,
                       fix="NOLOCK zorunluysa tabloyu native SQL sorgusu veya veritabanı view'ı ile oku.")

    # ===================================================== 3. VERİ TİPİ + KOLONLAR
    def analyze_columns(self):
        rel_keys = set()
        for rel in self.metadata.get('rels', []):
            rel_keys.add((rel['from_table'], rel['from_col']))
            rel_keys.add((rel['to_table'], rel['to_col']))

        string_dates, string_numbers, summed_ids = [], [], []
        for table in self.visible_tables:
            for col in table['cols']:
                name, dtype = col['name'], col['data_type']
                ref = f"{table['name']}[{name}]"
                if dtype == 'string' and is_date_value_name(name):
                    string_dates.append(ref)
                elif (dtype == 'string' and looks_numeric_name(name) and not is_dateish_name(name)
                      and (table['name'], name) not in rel_keys):
                    string_numbers.append(ref)
                folded = fold_name(name)
                if (dtype in NUMERIC_TYPES and col.get('summarize_by') not in (None, 'none')
                        and any(folded.endswith(tok) or folded.startswith(tok) for tok in ID_LIKE_TOKENS)):
                    summed_ids.append(ref)

        if string_dates:
            self._score('columns', 'high', f"Metin (string) olarak tutulan {len(string_dates)} tarih kolonu",
                        detail="Metin tarihler tarih tablosuna bağlanamaz, time intelligence çalışmaz ve "
                               "alfabetik sıralanır.",
                        evidence=string_dates,
                        fix="Kaynakta veya Power Query'de tipi Date/DateTime yap.",
                        penalty=capped_penalty(2, len(string_dates), 6))
        if string_numbers:
            self._score('columns', 'medium', f"Sayısal görünen ama metin tutulan {len(string_numbers)} kolon",
                        detail="Sayısal veriyi metin tutmak sıkıştırmayı bozar, toplama ve sıralamayı engeller.",
                        evidence=string_numbers,
                        fix="Int64/Decimal tipine çevir.",
                        penalty=capped_penalty(1, len(string_numbers), 4))
        if summed_ids:
            self._score('columns', 'low', "ID/yıl/kod kolonları varsayılan olarak toplanıyor",
                        evidence=summed_ids,
                        fix="Kolon özelliklerinde 'Summarize by' = 'Don't summarize' yap.",
                        penalty=capped_penalty(0.5, len(summed_ids), 2))

        unused = self.usage.unused_data_columns()
        if unused:
            self._score('columns', 'medium', f"Hiçbir yerde kullanılmayan {len(unused)} kolon",
                        detail="Görsel, filtre, ilişki, sıralama, RLS ya da kullanılan bir DAX ifadesinde geçmeyen "
                               "kolonlar boşuna yükleniyor ve bellek tüketiyor.",
                        evidence=unused,
                        fix="Bu kolonları SQL sorgusundan (veya Power Query'de Remove Columns ile) kaldır.",
                        penalty=capped_penalty(0.5, len(unused), 6))

    # ================================================================ 4. DAX
    def _dax_items(self):
        """(tür, ref, ifade, tablo, item) — measure'lar ve calculated column'lar."""
        items = []
        for measure in self.metadata.get('measures', []):
            if measure['table'] in self.profile.get('auto_date_tables', []):
                continue
            items.append(('measure', f"{measure['table']}[{measure['name']}]", measure.get('formula_full') or '',
                          measure['table'], measure))
        for table in self.visible_tables:
            for col in table['cols']:
                if col.get('kind') == 'calculated' and col.get('expression'):
                    items.append(('column', f"{table['name']}[{col['name']}]", col['expression'], table['name'], col))
        return items

    def analyze_dax(self):
        unused_measures = self.usage.unused_measures()
        unused_calc = self.usage.unused_calculated_columns()
        used_calc = [f"{t}[{c['name']}]" for t, c in self.usage.used_calculated_columns()]

        if unused_measures:
            self._score('dax', 'medium', f"Kullanılmayan {len(unused_measures)} measure",
                        detail="Hiçbir görselde, filtrede veya kullanılan başka bir measure'da geçmiyor.",
                        evidence=unused_measures,
                        fix="Measure'ı sil; ileride gerekecekse ayrı bir dokümanda sakla.",
                        penalty=capped_penalty(1, len(unused_measures), 3))
        if unused_calc:
            self._score('dax', 'medium', f"Kullanılmayan {len(unused_calc)} calculated column",
                        detail="Kullanılmadığı halde her refresh'te hesaplanıp bellekte tutuluyor.",
                        evidence=unused_calc,
                        fix="Calculated column'u modelden kaldır.",
                        penalty=capped_penalty(1, len(unused_calc), 3))
        if used_calc:
            self._score('dax', 'low', f"{len(used_calc)} calculated column kullanılıyor",
                        detail="Calculated column'lar refresh'te hesaplanır, sıkıştırması zayıftır ve RAM tüketir. "
                               "Zorunlu olmadıkça kaçınılmalı.",
                        evidence=used_calc,
                        fix="Satır bazlı hesapları SQL'e veya Power Query'ye, toplam hesaplarını measure'a taşı.",
                        penalty=capped_penalty(0.5, len(used_calc), 2))

        checks = defaultdict(list)
        excel_funcs, quick_measures, no_format = [], [], []
        measure_names = {m['name'].lower(): m['name'] for m in self.metadata.get('measures', [])}

        for kind, ref, expression, table_name, item in self._dax_items():
            code = strip_dax(expression).lower()
            label = ref + (" (calculated column)" if kind == 'column' else "")

            used_excel = [fn for fn in EXCEL_ONLY_FUNCTIONS if re.search(rf'\b{fn}\s*\(', code)]
            if used_excel:
                excel_funcs.append(f"{ref}: {', '.join(f.upper() for f in used_excel)}")
            if re.search(r'calculate(?:table)?\s*\((?:[^()]|\([^()]*\))*?\bfilter\s*\(', code, flags=re.DOTALL):
                checks['filter_in_calc'].append(label)
            iterators = [fn for fn in ITERATOR_FUNCTIONS if re.search(rf'\b{fn}\s*\(', code)]
            if len(iterators) >= 2:
                checks['multi_iter'].append(f"{label}: {', '.join(i.upper() for i in iterators)}")
            if re.search(rf"\b(?:{'|'.join(ITERATOR_FUNCTIONS)})\s*\(\s*'?[\w ]+'?\s*,", code) \
                    and not re.search(r'\b(?:values|distinct|filter|summarize|topn)\s*\(', code):
                checks['full_table_iter'].append(label)
            if re.search(r'[\)\]\w]\s*/\s*[\(\[\w]', code) and 'divide(' not in code:
                checks['raw_division'].append(label)
            if len(re.findall(r'\bcalculate\s*\(', code)) >= 3:
                checks['nested_calc'].append(label)
            if re.search(r'\bearlier(?:est)?\s*\(', code):
                checks['earlier'].append(label)
            if len(expression) > 400 and not re.search(r'\bvar\b', code):
                checks['long_no_var'].append(label)
            if re.search(r'\b(?:iferror|iserror)\s*\(', code):
                checks['iferror'].append(label)
            if not re.search(r'\bvar\b', code):
                refs = Counter(r.lower() for r in re.findall(r"(?<![\w'\]])\[([^\]]+)\]", code))
                repeated = [r for r, n in refs.items() if n >= 2 and r in measure_names]
                if repeated:
                    checks['repeated_measure'].append(f"{label}: [{measure_names[repeated[0]]}]")
            if kind == 'column' and re.search(r'\bcalculate\s*\(', code):
                checks['calc_col_calculate'].append(label)
            if kind == 'measure':
                if re.search(r'\bformat\s*\(', code):
                    checks['format_in_measure'].append(label)
                if 'isonorafter' in code:
                    quick_measures.append(ref)
                if not item.get('format_string'):
                    no_format.append(ref)

        rules = [
            ('filter_in_calc', 'medium', "CALCULATE içinde tablo filtresi (FILTER)",
             "FILTER(Tablo, …) tabloyu satır satır dolaşır; boolean filtre storage engine'de çok daha hızlı çözülür.",
             "CALCULATE(…, Tablo[Kolon] = X) kullan; FILTER gerekiyorsa tablo yerine kolon üzerinde çalıştır "
             "(FILTER(VALUES(Tablo[Kolon]), …)).", 1, 3),
            ('multi_iter', 'high', "Birden fazla iterator içeren ifade",
             "İç içe iterator'lar formula engine'de satır × satır maliyet üretir.",
             "Ara sonuçları VAR ile sakla; mümkünse SUM/COUNTROWS gibi basit aggregasyon kullan.", 1.5, 3),
            ('full_table_iter', 'medium', "Tüm tabloyu dolaşan iterator",
             "Iterator'a çıplak tablo verildiğinde her satır işlenir; büyük fact tablolarında yavaştır.",
             "Iterator'ı VALUES(Tablo[Kolon]) gibi daha küçük bir küme üzerinde çalıştır.", 1, 2),
            ('raw_division', 'medium', "DIVIDE yerine '/' operatörü",
             "Payda sıfır olduğunda '/' hata veya sonsuz değer döndürür.",
             "DIVIDE(pay, payda, 0) kullan.", 1, 2),
            ('calc_col_calculate', 'medium', "Calculated column içinde CALCULATE",
             "Calculated column'da CALCULATE her satır için context transition yapar; büyük tablolarda refresh'i ciddi "
             "yavaşlatır.",
             "Hesabı measure'a veya kaynak sorguya taşı; ilişkili değer gerekiyorsa RELATED kullan.", 1, 2),
            ('repeated_measure', 'low', "Aynı measure ifade içinde birden fazla kez hesaplanıyor",
             "VAR olmadan tekrar edilen measure her seferinde yeniden hesaplanır.",
             "Değeri bir kez VAR ile hesaplayıp tekrar kullan.", 0.5, 1.5),
            ('nested_calc', 'low', "Çok sayıda CALCULATE içeren ifade",
             "", "Tekrarlanan bağlamları VAR ile tek seferde hesapla.", 0.5, 1),
            ('earlier', 'low', "EARLIER kullanımı",
             "EARLIER okunması zor ve eski bir kalıptır.", "Dış satır değerini VAR ile yakala.", 0.5, 1),
            ('iferror', 'low', "IFERROR/ISERROR kullanımı",
             "Hata yakalama fonksiyonları formula engine'i yavaşlatır.",
             "Hatayı önleyen fonksiyonları kullan (DIVIDE, ISBLANK, COALESCE).", 0.5, 1),
            ('format_in_measure', 'low', "Measure içinde FORMAT",
             "FORMAT metin döndürür; sayısal sıralama ve toplama bozulur, sorgu yavaşlar.",
             "Biçimlendirmeyi measure'ın format string'i ile yap.", 0.5, 1),
            ('long_no_var', 'low', "Uzun ve VAR kullanmayan ifade",
             "", "İfadeyi VAR bloklarına böl; okunabilirlik artar, tekrar hesaplama azalır.", 0.5, 1),
        ]
        for key, severity, title, detail, fix, unit, cap in rules:
            if checks.get(key):
                self._score('dax', severity, title, detail=detail, evidence=checks[key], fix=fix,
                            penalty=capped_penalty(unit, len(checks[key]), cap))

        if excel_funcs:
            self._note('query', 'DAX', "DAX'ta bulunmayan Excel fonksiyonları",
                       detail="COUNTIF/SUMIFS gibi fonksiyonlar DAX'ta yoktur; measure hata verir.",
                       evidence=excel_funcs,
                       fix="CALCULATE([Measure], Tablo[Kolon] = \"Değer\") kalıbını kullan.")
        if quick_measures:
            self._note('query', 'DAX', "Quick measure şablonu (running total / ISONORAFTER)",
                       detail="Otomatik üretilen running total kalıbı büyük veride yavaşlar.",
                       evidence=quick_measures,
                       fix="Tarih tablosu kurulduktan sonra DATESYTD veya WINDOW tabanlı kalıba geç.")
        if no_format:
            self._note('query', 'DAX', "Format string tanımlı olmayan measure'lar",
                       evidence=no_format, fix="Measure'lara sayı/yüzde formatı ver.")

    # ========================================================= 5. GÖRSELLEŞTİRME
    def analyze_density(self):
        pages = (self.metadata.get('report_layout') or {}).get('pages', [])
        if not pages:
            self._score('density', 'medium', "Report/Layout verisi bulunamadı",
                        detail="Görsel kontrolleri yapılamadı.", penalty=5)
            return
        dense, penalty = [], 0.0
        per_visual = f"{round(1.5 * self._factor('density'), 2):g}".replace('.', ',')
        for page in pages:
            count = page.get('data_visual_count', 0)
            if count > DENSITY_LIMIT:
                dense.append(f"{page['name']} ({count} görsel)")
                penalty += 1.5 * (count - DENSITY_LIMIT)
        if dense:
            self._score('density', 'high' if penalty >= 5 else 'medium',
                        f"{DENSITY_LIMIT}'den fazla görsel içeren {len(dense)} sayfa",
                        detail=f"Her görsel ayrı sorgu üretir ve sayfa açılışını yavaşlatır. Sınır: sayfa başına "
                               f"{DENSITY_LIMIT} veri görseli (slicer, metin kutusu, şekil, resim ve butonlar sayılmaz). "
                               f"Sınırı aşan her görsel {per_visual} puan kırar.",
                        evidence=dense,
                        fix="Sayfayı böl; ikincil görselleri drill-through veya tooltip sayfasına taşı.",
                        penalty=penalty)
        empty = [p['name'] for p in pages if p.get('visual_count', 0) == 0]
        if empty:
            self._note('visualization', 'Görsel yoğunluğu', "Görsel içermeyen sayfalar",
                       evidence=empty, fix="Boş sayfaları kaldır veya gizle.")

    def analyze_naming(self):
        result = evaluate_naming(self.metadata)
        total = result['total']
        violations = result['violations']
        if not total or not violations:
            return
        bucket_points = PENALTY_SCALE['naming']
        per_object = bucket_points / total
        penalty_by_reason = defaultdict(float)
        for item in violations:
            share = per_object / len(item['reasons'])
            for reason in item['reasons']:
                penalty_by_reason[reason] += share

        compliant = total - len(violations)
        details = {
            'unclear': ("Varsayılan (Column1, Sayfa 1) veya çok kısa adlar ne gösterdiğini anlatmıyor.",
                        "İçeriği anlatan bir ad ver (örn. Column1 → SiparisTarihi)."),
            'turkish': ("Türkçe karakterler bazı araçlarda (DAX Studio, API, export) sorun çıkarır.",
                        "ç→c, ğ→g, ı→i, ö→o, ş→s, ü→u kullan."),
            'pascal': ("Adlar boşluk, alt çizgi veya tire içermemeli; her kelime büyük harfle başlamalı "
                       "(bilinen kısaltmalar serbest: ID, KPI, YTD…).",
                       "Önerilen adlar listede."),
        }
        for reason in ('unclear', 'turkish', 'pascal'):
            items = result['by_reason'][reason]
            if not items:
                continue
            detail, fix = details[reason]
            evidence = [f"{i['kind_label']}: {i['ref']} → {i['suggestion']}" for i in items]
            self._score('naming', 'low' if reason == 'pascal' else 'medium',
                        f"{REASON_LABELS[reason]}: {len(items)}",
                        detail=f"{detail} Standarda uyan ad oranı: {compliant}/{total}.",
                        evidence=evidence, fix=fix,
                        penalty=round(penalty_by_reason[reason], 1))

    def analyze_chart_fit(self):
        self.visual_reviews = evaluate_report(self.metadata)
        errors, suggestions = [], []
        for review in self.visual_reviews:
            label = f"{review['page']} / {review['title'] or review['type_label']}"
            for level, text, recommendation in review['issues']:
                (errors if level == 'error' else suggestions).append((label, text, recommendation))

        for label, text, recommendation in errors:
            self._score('chart_fit', 'medium', f"Uygun olmayan grafik: {label}",
                        detail=text, fix=recommendation, penalty=1.5)
        for label, text, recommendation in suggestions:
            self._note('visualization', 'Grafik uygunluğu', f"Grafik önerisi: {label}",
                       detail=text, fix=recommendation)

    # ============================================= bilgi notları (puan kırmaz)
    def analyze_info_notes(self):
        auto_dates = self.profile.get('auto_date_tables', [])
        if auto_dates:
            self._note('modeling', 'Calendar dimension', "Auto date/time açık",
                       detail=f"{len(auto_dates)} gizli tarih tablosu üretilmiş; model boyutunu ve refresh süresini artırır.",
                       fix="File > Options > Current File > Data Load > 'Auto date/time'ı kapat.")

        fact_like = self._structure()[2]
        mode_counter = Counter()
        direct_query, no_incremental, calculated_tables = [], [], []
        for table in self.visible_tables:
            mode = table.get('partition_mode') or 'import'
            mode_counter[mode] += 1
            lower = (table.get('query') or '').lower()
            if mode == 'directQuery':
                direct_query.append(table['name'])
            if table.get('partition_source_type') == 'calculated':
                calculated_tables.append(table['name'])
            if table['name'] in fact_like and mode == 'import' and not ('rangestart' in lower and 'rangeend' in lower):
                no_incremental.append(table['name'])
        if no_incremental:
            self._note('query', 'Refresh', "Fact tablolarında incremental refresh tanımlı değil",
                       detail="Her refresh'te tüm geçmiş yeniden yüklenir.",
                       evidence=no_incremental,
                       fix="RangeStart/RangeEnd parametreleriyle incremental refresh politikası kur.")
        if direct_query:
            self._note('query', 'Refresh', "DirectQuery tabloları", evidence=direct_query,
                       detail="Her görsel etkileşimi kaynağa sorgu gönderir.")
        if calculated_tables:
            self._note('query', 'Refresh', "Calculated table'lar refresh'te yeniden hesaplanır", evidence=calculated_tables)
        if mode_counter:
            self._note('query', 'Refresh', "Depolama modu dağılımı",
                       detail=', '.join(f"{mode}: {count}" for mode, count in mode_counter.items()))

    # ======================================================= KAPSAM (uygulanabilirlik)
    def has_sql_source(self):
        """En az bir tablo veritabanından (native SQL veya navigation ile) okunuyor mu?"""
        for table in self.visible_tables:
            if table.get('partition_source_type') != 'm':
                continue
            lower = (table.get('query') or '').lower()
            if self._is_native_sql(lower) or any(conn in lower for conn in DB_CONNECTORS):
                return True
        return False

    def has_dax(self):
        """Modelde measure veya calculated column var mı? (otomatik tarih tabloları hariç)"""
        return bool(self._dax_items())

    def determine_scope(self):
        self.applicability = {'sql': self.has_sql_source(), 'dax': self.has_dax()}
        self.scope_notes = {
            'sql': "Modelde SQL/veritabanı kaynağı yok",
            'dax': "Modelde measure veya calculated column yok",
        }
        self.weights = effective_weights(self.applicability)
        skipped = [key for key, ok in self.applicability.items() if not ok]
        if skipped:
            weights = self.weights
            moved = ', '.join(
                f"{BUCKET_INFO[k][1]} {round(weights[k], 1):g}".replace('.', ',')
                for k in ('sql', 'columns', 'dax') if weights[k]
            )
            reasons = '; '.join(self.scope_notes[k] for k in skipped)
            self._note('query', 'Puanlama kapsamı', "Bazı bölümler bu model için uygulanmadı",
                       detail=f"{reasons}. Bu bölümlerin puanı kategorideki diğer bölümlere dağıtıldı: {moved}.")

    # ================================================================ SKORLAMA
    def compute_scores(self):
        self.breakdown = compute_breakdown(self.findings, self.applicability, self.scope_notes)
        self.scores = {key: value['score'] for key, value in self.breakdown.items()}
        return self.scores

    def build_checklist(self):
        items = [f"{f.bucket_label}: {f.title} giderildi" for f in sort_findings(self.findings) if f.penalty > 0]
        items.append("Analiz yeniden çalıştırıldı ve skor hedefi (≥85) sağlandı")
        return items

    # ===================================================================== AI
    def run_ai_commentary(self, total_score):
        if not self.use_ai:
            self.ai_note = "AI yorumu kapalı."
            return None
        if not self.ai.available():
            self.ai_note = f"AI yorumu üretilemedi: {self.ai.last_error}"
            self._log(f"\n⚠️  {self.ai_note}")
            return None

        self._log("\n🤖 AI yorumu hazırlanıyor (Ollama / %s)..." % self.ai.model_name)
        commentary = self.ai.explain_findings(
            self.metadata, sort_findings(self.findings), self.breakdown, total_score, self.visual_reviews,
        )
        if commentary:
            self.ai_commentary = commentary
            self.ai_warnings = self.ai.find_unknown_references(commentary, self.metadata)
            if self.ai_warnings:
                self._log("⚠️  AI yorumunda modelde bulunmayan alanlar: " + ", ".join(self.ai_warnings))
        else:
            self.ai_note = f"AI yorumu üretilemedi: {self.ai.last_error}"
            self._log(f"⚠️  {self.ai_note}")
        return commentary

    # ================================================================ RAPOR
    def generate_final_report(self, write_html=True, json_path=None):
        scores = self.scores or self.compute_scores()
        total_score = sum(scores.values())
        status, description = self._status_for_score(total_score)

        self._log()
        self._log(self._box("BI SKORLAMA | KAPSAMLI RAPOR", [
            f"Dosya: {self.display_name}",
            f"Tarih: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}",
            f"Genel Durum: {status} | {description}",
        ]))

        lines = []
        for category, data in self.breakdown.items():
            lines.append(f"{data['label']:<26}{self._draw_score_bar(data['score'], data['max'])}")
            for bucket in data['buckets']:
                if bucket['applicable']:
                    lines.append(f"   {bucket['label'][:38]:<38} {bucket['score']:>5g} / {bucket['max']:g}")
                else:
                    lines.append(f"   {bucket['label'][:38]:<38}     — uygulanmadı")
        lines.append(f"{'GENEL SKOR':<26}{self._draw_score_bar(total_score, sum(self.category_max.values()))}")
        self._log()
        self._log(self._box("PUAN DAĞILIMI", lines))

        self.run_ai_commentary(total_score)
        if self.ai_commentary:
            self._log("\n" + "=" * 80 + "\n🤖 AI YORUMU VE DÜZELTME PLANI\n" + "=" * 80)
            self._log(self.ai_commentary)

        outputs = []
        if write_html:
            html_content = self.render_html()
            report_base = Path(self.pbit_file).with_suffix("")
            unique_path = report_base.with_name(f"{report_base.name}_report.html")
            legacy_path = Path(self.pbit_file).with_name("FINAL_REPORT.html")
            unique_path.write_text(html_content, encoding="utf-8")
            legacy_path.write_text(html_content, encoding="utf-8")
            outputs.extend([str(unique_path), str(legacy_path)])
        if json_path:
            Path(json_path).write_text(
                json.dumps(self.summary(include_findings=True), ensure_ascii=False, indent=2), encoding="utf-8",
            )
            outputs.append(str(json_path))
        if outputs:
            self._log()
            self._log(self._box("ÇIKTILAR", [f"• {path}" for path in outputs]))
        return total_score

    # ======================================================= ARAYÜZ İÇİN API
    @property
    def total_score(self):
        return sum((self.scores or self.compute_scores()).values())

    def render_html(self, nav_html=None):
        scores = self.scores or self.compute_scores()
        total_score = sum(scores.values())
        status, description = self._status_for_score(total_score)
        return build_html_report(
            pbit_file=self.display_name,
            metadata=self.metadata,
            findings=self.findings,
            breakdown=self.breakdown,
            total_score=total_score,
            status=status,
            description=description,
            checklist=self.build_checklist(),
            visual_reviews=self.visual_reviews,
            ai_commentary=self.ai_commentary,
            ai_note=self.ai_note,
            ai_warnings=self.ai_warnings,
            nav_html=nav_html,
        )

    def summary(self, include_findings=False):
        scores = self.scores or self.compute_scores()
        total_score = sum(scores.values())
        status, _ = self._status_for_score(total_score)
        payload = {
            "file": self.display_name,
            "generated_at": datetime.now().isoformat(timespec='seconds'),
            "total_score": round(total_score, 1),
            "status": status,
            "scores": {k: round(v, 1) for k, v in scores.items()},
            "finding_count": sum(1 for f in self.findings if f.penalty > 0),
            "ai_used": bool(self.ai_commentary),
            "ai_warning_count": len(self.ai_warnings),
        }
        if include_findings:
            payload.update({
                "breakdown": self.breakdown,
                "profile": self.profile,
                "findings": [f.as_dict() for f in sort_findings(self.findings)],
                "visual_reviews": [
                    {k: v for k, v in r.items() if k != 'fields'} for r in self.visual_reviews
                ],
                "ai_commentary": self.ai_commentary,
                "ai_note": self.ai_note,
            })
        return payload

    # ================================================================ AKIŞ
    def run_rules(self):
        """Tüm kural analizlerini çalıştırıp skoru hesaplar. AI'ya dokunmaz."""
        self.findings = []
        self.usage = UsageAnalysis(self.metadata)
        # Kapsam kurallardan önce belirlenir: kesintiler kovanın geçerli ağırlığıyla ölçeklenir
        self.determine_scope()
        if self.findings:
            self._section("ℹ️  PUANLAMA KAPSAMI", self.findings)
        sections = [
            ("🏗️  1a. STAR SCHEMA", self.analyze_star_schema),
            ("🔗 1b. İLİŞKİLER VE CALENDAR", self.analyze_relationships),
            ("🧾 2a. SQL SORGULARI", self.analyze_sql),
            ("🔍 2b. VERİ TİPİ VE KULLANILMAYAN KOLONLAR", self.analyze_columns),
            ("⚡ 2c. DAX", self.analyze_dax),
            ("📊 3a. GÖRSEL YOĞUNLUĞU", self.analyze_density),
            ("🏷️  3b. İSİMLENDİRME", self.analyze_naming),
            ("📈 3c. GRAFİK UYGUNLUĞU", self.analyze_chart_fit),
            ("ℹ️  BİLGİ NOTLARI", self.analyze_info_notes),
        ]
        for title, method in sections:
            self._run_section(title, method)
        return sum(self.compute_scores().values())

    def run(self, write_html=True, json_path=None):
        if not self.ok:
            print(f"❌ {self.metadata}")
            return None
        self.run_rules()
        return self.generate_final_report(write_html=write_html, json_path=json_path)


def build_arg_parser():
    parser = argparse.ArgumentParser(
        description="Power BI (.pbit) dosyasını kural tabanlı denetler, isteğe bağlı olarak AI ile yorumlar.",
    )
    parser.add_argument("pbit_file", help="Analiz edilecek .pbit dosyası")
    parser.add_argument("--no-ai", action="store_true", help="LLM yorumunu atla, sadece kural motorunu çalıştır")
    parser.add_argument("--model", default=DEFAULT_MODEL, help=f"Ollama model adı (varsayılan: {DEFAULT_MODEL})")
    parser.add_argument("--json", dest="json_path", help="Bulguları bu JSON dosyasına da yaz")
    parser.add_argument("--no-html", action="store_true", help="HTML rapor üretme")
    return parser


def main(argv=None):
    args = build_arg_parser().parse_args(argv)
    print("\n🚀 BI SKORLAMA | KAPSAMLI ANALİZ")
    print("=" * 80)
    if not Path(args.pbit_file).exists():
        print(f"❌ Dosya bulunamadı: {args.pbit_file}")
        return 1
    analyzer = ComprehensiveAnalyzer(args.pbit_file, model_name=args.model, use_ai=not args.no_ai)
    score = analyzer.run(write_html=not args.no_html, json_path=args.json_path)
    return 0 if score is not None else 1


if __name__ == "__main__":
    sys.exit(main())
