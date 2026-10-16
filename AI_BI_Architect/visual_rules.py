#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Görsel türü ile gösterilen verinin yapısı uyumlu mu?

Her görselin alanları anlamına göre sınıflandırılır:
  zaman     : tarih tipi, tarih hiyerarşisi veya yıl/ay/gün/dönem gibi zaman parçaları
  coğrafya  : Power BI veri kategorisi (Ülke, Şehir, Enlem...) veya coğrafi ad
  kategori  : diğer metin/kategorik alanlar
  ölçü      : measure, aggregation veya toplanan sayısal kolon

Sonra veri yapısı -> doğru görsel tablosuna göre değerlendirilir:
  error   : açık hata, puan kırar
  suggest : daha iyi bir alternatif var, bilgi notu
.pbit dosyasında veri satırı olmadığı için dilim/kategori SAYISI bilinemez;
kontroller yalnızca görselin yapısına dayanır.
"""

from pbit_parser import NUMERIC_TYPES, is_date_value_name, is_dateish_name, name_tokens

LINE = {'lineChart', 'areaChart', 'stackedAreaChart'}
COMBO = {'lineClusteredColumnComboChart', 'lineStackedColumnComboChart'}
BAR = {
    'barChart', 'columnChart', 'clusteredBarChart', 'clusteredColumnChart',
    'hundredPercentStackedBarChart', 'hundredPercentStackedColumnChart', 'ribbonChart',
}
PIE = {'pieChart', 'donutChart'}
TREEMAP = {'treemap'}
FUNNEL = {'funnel'}
SCATTER = {'scatterChart'}
MAP = {'map', 'filledMap', 'shapeMap', 'azureMap'}
CARD = {'card', 'multiRowCard', 'cardVisual', 'kpi'}
GAUGE = {'gauge'}
TABLE = {'tableEx', 'pivotTable'}
WATERFALL = {'waterfallChart'}

VISUAL_LABELS = {
    'lineChart': 'Çizgi grafik', 'areaChart': 'Alan grafik', 'stackedAreaChart': 'Yığılmış alan',
    'lineClusteredColumnComboChart': 'Çizgi + sütun', 'lineStackedColumnComboChart': 'Çizgi + yığılmış sütun',
    'barChart': 'Yığılmış çubuk', 'columnChart': 'Yığılmış sütun', 'clusteredBarChart': 'Kümelenmiş çubuk',
    'clusteredColumnChart': 'Kümelenmiş sütun', 'hundredPercentStackedBarChart': '%100 çubuk',
    'hundredPercentStackedColumnChart': '%100 sütun', 'ribbonChart': 'Şerit grafik',
    'pieChart': 'Pasta grafik', 'donutChart': 'Halka grafik', 'treemap': 'Treemap', 'funnel': 'Huni',
    'scatterChart': 'Dağılım (scatter)', 'map': 'Harita', 'filledMap': 'Dolgulu harita',
    'shapeMap': 'Şekil haritası', 'azureMap': 'Azure harita', 'card': 'Kart', 'multiRowCard': 'Çok satırlı kart',
    'cardVisual': 'Kart', 'kpi': 'KPI', 'gauge': 'Gösterge', 'tableEx': 'Tablo', 'pivotTable': 'Matris',
    'waterfallChart': 'Şelale', 'slicer': 'Slicer',
}

TIME_DATA_CATEGORIES = {
    'years', 'months', 'quarters', 'days', 'monthofyear', 'quarterofyear', 'dayofmonth',
    'dayofweek', 'paddeddatetabledates', 'time',
}
GEO_DATA_CATEGORIES = {
    'country', 'city', 'stateorprovince', 'continent', 'county', 'postalcode',
    'place', 'address', 'latitude', 'longitude',
}
GEO_NAME_TOKENS = {
    'ulke', 'sehir', 'il', 'ilce', 'country', 'city', 'state', 'eyalet', 'posta', 'postakodu',
    'latitude', 'longitude', 'enlem', 'boylam', 'koordinat', 'continent', 'kita',
}
VALUE_ROLES = {'Y', 'Y2', 'Values', 'Size', 'TargetValue', 'Indicator', 'Goal', 'MaxValue',
               'MinValue', 'Gradient', 'ColorSaturation'}
AXIS_ROLES = {'Category', 'Axis', 'Rows', 'Columns', 'Legend', 'Series', 'Group', 'Details', 'Location'}
IGNORED_ROLES = {'Tooltips'}


def _column_index(metadata):
    index = {}
    for table in metadata.get('tables', []):
        for col in table['cols']:
            index[(table['name'], col['name'])] = col
    return index


def classify_field(field, columns):
    """Bir görsel alanının anlamını döndürür: ('time'|'geo'|'category'|'measure', tarih_değeri_mi)"""
    if field['kind'] in ('measure', 'aggregation'):
        return 'measure', False
    col = columns.get((field.get('table'), field.get('field'))) or {}
    name = field.get('field') or ''
    data_type = col.get('data_type')
    category = (col.get('data_category') or '').lower()

    # Görselde örtük olarak toplanan sayısal kolon bir ölçüdür; adında "günlük" gibi
    # zaman kelimesi geçse bile (örn. GunlukSikayetSayisi) eksen değildir.
    if (data_type in NUMERIC_TYPES and col.get('summarize_by') not in (None, 'none')
            and category not in TIME_DATA_CATEGORIES):
        return 'measure', False

    strong_date = bool(field.get('date_hierarchy_level')) or data_type in ('dateTime', 'date') or is_date_value_name(name)
    if strong_date or category in TIME_DATA_CATEGORIES or is_dateish_name(name):
        return 'time', strong_date
    if category in GEO_DATA_CATEGORIES or any(tok in GEO_NAME_TOKENS for tok in name_tokens(name)):
        return 'geo', False
    return 'category', False


def describe_fields(fields):
    labels = {'time': 'zaman', 'geo': 'coğrafya', 'category': 'kategori', 'measure': 'ölçü'}
    parts = []
    for f in fields:
        parts.append(f"{f['field']} ({labels[f['semantic']]})")
    return ', '.join(parts)


def evaluate_visual(visual, columns):
    """Görseli değerlendirir. Dönen sözlük raporda ve AI prompt'unda kullanılır."""
    vtype = visual['type']
    result = {
        "page": visual['page'],
        "type": vtype,
        "type_label": VISUAL_LABELS.get(vtype, vtype),
        "title": visual.get('title'),
        "issues": [],
        "verdict": "ok",
    }
    if visual.get('is_decorative') or visual.get('is_slicer'):
        result['verdict'] = 'skip'
        return result

    fields = []
    for f in visual.get('fields', []):
        if f.get('role') in IGNORED_ROLES:
            continue
        semantic, strong_date = classify_field(f, columns)
        fields.append(dict(f, semantic=semantic, strong_date=strong_date))
    result['fields'] = fields
    result['field_summary'] = describe_fields(fields)

    measures = [f for f in fields if f['semantic'] == 'measure']
    dims = [f for f in fields if f['semantic'] != 'measure']
    # Tablo/matriste kategoriler de "Values" rolünde durur; orada tüm boyutlar eksen sayılır
    axis_dims = [f for f in dims if vtype in TABLE or f.get('role') not in VALUE_ROLES]
    has_time = any(f['semantic'] == 'time' for f in axis_dims)
    has_strong_date = any(f['strong_date'] for f in axis_dims)
    has_geo = any(f['semantic'] == 'geo' for f in dims)

    def error(text, recommendation):
        result['issues'].append(('error', text, recommendation))

    def suggest(text, recommendation):
        result['issues'].append(('suggest', text, recommendation))

    if not fields:
        result['verdict'] = 'skip'
        return result

    if vtype in PIE:
        if len(measures) > 1:
            error("Pasta/halka grafikte birden fazla ölçü var; dilimler farklı ölçülerden oluşamaz.",
                  "Ölçüleri karşılaştırmak için kümelenmiş çubuk grafik kullan.")
        if len(axis_dims) > 1:
            error("Pasta/halka grafikte birden fazla kategori/legend alanı var.",
                  "Yığılmış çubuk grafik veya treemap kullan.")
        if not axis_dims and measures:
            error("Kategorisi olmayan pasta grafik tek bir değer gösteriyor.", "Kart görseli kullan.")
        if has_time:
            error("Zaman serisi parça-bütün grafiğinde gösteriliyor; zaman içindeki değişim okunamaz.",
                  "Çizgi grafik kullan.")

    elif vtype in TREEMAP or vtype in FUNNEL:
        if has_time:
            error(f"Zaman serisi {result['type_label'].lower()} ile gösteriliyor.", "Çizgi grafik kullan.")
        if vtype in FUNNEL and not axis_dims:
            error("Aşamaları olmayan huni grafik.", "Kart veya çubuk grafik kullan.")

    elif vtype in LINE:
        if axis_dims and not has_time:
            error("Çizgi grafik kategorik bir eksende kullanılmış; çizgi, kategoriler arasında süreklilik varmış "
                  "izlenimi verir.", "Kategorileri karşılaştırmak için çubuk/sütun grafik kullan.")
        if not axis_dims and len(measures) == 1:
            error("Ekseni olmayan çizgi grafik tek bir değer gösteriyor.", "Kart görseli kullan.")

    elif vtype in BAR:
        if not axis_dims and len(measures) == 1:
            error("Kategorisi olmayan çubuk/sütun grafik tek bir değer gösteriyor.", "Kart görseli kullan.")
        if has_strong_date:
            suggest("Tarih ekseninde zaman içindeki değişim çizgi grafikle daha net okunur.",
                    "Çizgi grafik kullan (az sayıda dönem için sütun grafik de kabul edilebilir).")
        if len(measures) > 4:
            suggest(f"Tek grafikte {len(measures)} ölçü var; seriler ayırt edilmesi zor hale gelir.",
                    "Grafiği böl veya small multiples kullan.")
        if has_geo:
            suggest("Coğrafi alan çubuk grafikte gösteriliyor.",
                    "Bölgesel dağılımı göstermek önemliyse harita düşünülebilir.")

    elif vtype in COMBO:
        if len(measures) > 4:
            suggest(f"Kombine grafikte {len(measures)} ölçü var.", "Grafiği sadeleştir.")

    elif vtype in SCATTER:
        axis_fields = [f for f in fields if f.get('role') in ('X', 'Y')]
        if any(f['semantic'] != 'measure' for f in axis_fields):
            error("Dağılım grafiğinin X/Y ekseninde kategorik alan var; scatter iki ölçünün ilişkisini gösterir.",
                  "Kategoriyi Details alanına taşı veya çubuk grafik kullan.")

    elif vtype in MAP:
        if not has_geo:
            error("Haritada coğrafi bir alan (ülke, şehir, enlem/boylam) yok.",
                  "Coğrafi alan ekle veya çubuk grafik kullan.")

    elif vtype in GAUGE:
        roles = {f.get('role') for f in fields}
        if not roles & {'TargetValue', 'MaxValue'}:
            suggest("Hedef veya maksimum değeri olmayan gösterge (gauge).",
                    "Hedef değer ekle ya da kart kullan.")

    elif vtype in TABLE:
        if has_strong_date and measures and len(fields) <= 3:
            suggest("Tablo bir zaman serisi gösteriyor; eğilim tablodan zor okunur.",
                    "Zaman içindeki değişim için çizgi grafik kullan; detay gerekiyorsa tabloyu drill-through sayfasına al.")
        if not measures and len(fields) > 8:
            suggest(f"Ölçüsüz {len(fields)} kolonlu ham veri tablosu.",
                    "Kolon sayısını azalt veya export amaçlı ayrı sayfaya taşı.")

    elif vtype in WATERFALL:
        if not axis_dims:
            error("Kategorisi olmayan şelale grafik.", "Kart kullan veya kategori ekle.")

    levels = [level for level, _, _ in result['issues']]
    if 'error' in levels:
        result['verdict'] = 'error'
    elif 'suggest' in levels:
        result['verdict'] = 'suggest'
    return result


def evaluate_report(metadata):
    columns = _column_index(metadata)
    layout = metadata.get('report_layout', {}) or {}
    return [evaluate_visual(v, columns) for v in layout.get('visuals', [])]
