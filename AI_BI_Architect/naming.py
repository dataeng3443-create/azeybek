#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""İsimlendirme standardı: anlaşılır, PascalCase, Türkçe karakter içermeyen adlar.

Kontrol edilen nesneler: sayfalar, tablolar, kolonlar (gizliler dahil),
calculated column'lar ve measure'lar. Otomatik tarih tabloları ve sistem
kolonları (RowNumber) kapsam dışıdır.
"""

import re

from pbit_parser import TR_FOLD_MAP

TURKISH_CHARS = set('çğıöşüÇĞİÖŞÜ')

# Bilinen kısaltmalar: tamamı büyük harf olsa da PascalCase sayılır (örn. MusteriID, KPIHedef)
ABBREVIATIONS = {
    'ID', 'KPI', 'YTD', 'MTD', 'QTD', 'WTD', 'YOY', 'MOM', 'WOW', 'PY', 'CY', 'LY', 'TY',
    'KDV', 'SKU', 'TL', 'TRY', 'USD', 'EUR', 'GBP', 'URL', 'API', 'SLA', 'CRM', 'ERP', 'POS',
    'IBAN', 'TCKN', 'VKN', 'GSM', 'PDF', 'AVG', 'MAX', 'MIN', 'NPS', 'ROI', 'CTR', 'KM', 'KG',
    'IK', 'HR', 'IT', 'AR', 'AP', 'GL', 'BI', 'UK', 'US', 'AB', 'EU', 'OTV', 'SGK', 'EFT',
    'ATM', 'PK', 'FK', 'UTC', 'GMT', 'ISO', 'QR', 'IP', 'UI', 'FTE', 'COGS', 'EBITDA', 'MRR',
    'ARR', 'CAC', 'LTV', 'AOV', 'B2B', 'B2C',
}

DEFAULT_NAME = re.compile(
    r'^(column|sutun|kolon|page|sayfa|table|tablo|query|sorgu|measure|olcu|field|alan|'
    r'new|yeni|untitled|adsiz|calculated column|hesaplanmis kolon)[\s_\-]*\d*$',
    re.IGNORECASE,
)
_TOKEN = re.compile(r'[A-Z]+(?=[A-Z][a-z])|[A-Z][a-z]+|[A-Z]+|[a-z]+|\d+')

KIND_LABELS = {
    'page': 'Sayfa',
    'table': 'Tablo',
    'column': 'Kolon',
    'calculated_column': 'Calculated column',
    'measure': 'Measure',
}

REASON_LABELS = {
    'unclear': 'Anlaşılır olmayan ad',
    'turkish': 'Türkçe karakter içeren ad',
    'pascal': 'PascalCase olmayan ad',
}


def has_turkish(name):
    return any(ch in TURKISH_CHARS for ch in name)


def is_pascal_case(name):
    """Boşluk/alt çizgi/tire yok, büyük harfle başlar, büyük harf blokları bilinen kısaltma."""
    if not re.fullmatch(r'[A-Za-z0-9]+', name) or not name[0].isalpha() or not name[0].isupper():
        return False
    for token in _TOKEN.findall(name):
        if len(token) > 1 and token.isupper() and token not in ABBREVIATIONS:
            return False
    return True


def is_unclear(name):
    folded = name.translate(TR_FOLD_MAP).strip()
    if DEFAULT_NAME.match(folded):
        return True
    compact = re.sub(r'[^A-Za-z0-9]', '', folded)
    if compact.isdigit():
        return True
    # Tek karakterli adlar anlam taşımaz; 2 harfliler (Ay, Il, No) Türkçede anlamlı olabilir
    return len(compact) <= 1


def suggest_name(name):
    """'Şikayet Sayısı' -> 'SikayetSayisi', 'CM_Ad_Soyad' -> 'CMAdSoyad'"""
    folded = name.translate(TR_FOLD_MAP)
    words = re.split(r'[^A-Za-z0-9]+', folded)
    parts = []
    for word in words:
        for token in _TOKEN.findall(word) or ([word] if word else []):
            if token.isupper() and token in ABBREVIATIONS:
                parts.append(token)
            elif token.isdigit():
                parts.append(token)
            else:
                parts.append(token[:1].upper() + token[1:].lower() if token.isupper() and len(token) > 1
                             else token[:1].upper() + token[1:])
    return ''.join(parts) or name


def check_name(name):
    reasons = []
    if is_unclear(name):
        reasons.append('unclear')
    if has_turkish(name):
        reasons.append('turkish')
    # Türkçe karakterler ayrıca sayıldığı için PascalCase kontrolü onlar düzeltilmiş halde yapılır
    if not is_pascal_case(name.translate(TR_FOLD_MAP)):
        reasons.append('pascal')
    return reasons


def collect_names(metadata):
    objects = []
    for page in (metadata.get('report_layout') or {}).get('pages', []):
        objects.append(('page', page['name'], page['name']))
    for table in metadata.get('visible_tables', []):
        objects.append(('table', table['name'], table['name']))
        for col in table['cols']:
            if col.get('kind') == 'rowNumber':
                continue
            kind = 'calculated_column' if col.get('is_calculated') else 'column'
            objects.append((kind, col['name'], f"{table['name']}[{col['name']}]"))
        for measure in table.get('measures', []):
            objects.append(('measure', measure['name'], f"{table['name']}[{measure['name']}]"))
    return objects


def evaluate_naming(metadata):
    """Her nesnenin adını kontrol eder.

    Dönen sözlük: toplam nesne, uyumsuz nesneler ve sebep bazında liste.
    """
    objects = collect_names(metadata)
    violations = []
    by_reason = {key: [] for key in REASON_LABELS}
    for kind, name, ref in objects:
        reasons = check_name(name)
        if not reasons:
            continue
        suggestion = suggest_name(name)
        item = {
            "kind": kind,
            "kind_label": KIND_LABELS[kind],
            "name": name,
            "ref": ref,
            "reasons": reasons,
            "suggestion": suggestion,
        }
        violations.append(item)
        for reason in reasons:
            by_reason[reason].append(item)
    return {
        "total": len(objects),
        "violations": violations,
        "by_reason": by_reason,
    }
