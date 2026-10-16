#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Modeldeki kolon ve measure'ların gerçekten kullanılıp kullanılmadığını bulur.

Bir alan şu yollardan biriyle "kullanılıyor" sayılır:
  * Raporda bir görselde, görsel/sayfa/rapor filtresinde geçiyor
  * Bir ilişkinin anahtarı (otomatik tarih tabloları hariç)
  * Kullanılan bir kolonun "Sort by column" hedefi
  * RLS (rol) filtresinde veya calculated table ifadesinde geçiyor
  * KULLANILAN bir measure veya calculated column'un DAX ifadesinde geçiyor

Son madde zincirleme çalışır: sadece kullanılmayan bir measure'ın içinde geçen
kolon da kullanılmıyor sayılır (measure silinince o kolona gerek kalmaz).
"""

import re

_STRING = re.compile(r'"(?:[^"]|"")*"')
_COMMENTS = re.compile(r'//[^\n]*|--[^\n]*|/\*.*?\*/', re.DOTALL)
# 'Tablo Adı'[Kolon] veya Tablo[Kolon]
_QUALIFIED = re.compile(r"(?:'((?:[^']|'')+)'|([A-Za-z_À-ɏ][\wÀ-ɏ]*))\s*\[([^\]]+)\]")
_BRACKET = re.compile(r"\[([^\]]+)\]")


def strip_dax(expression):
    """Yorumları ve metin sabitlerini çıkarır (içlerindeki köşeli parantezler yanıltmasın)."""
    text = _COMMENTS.sub(' ', expression or '')
    return _STRING.sub('""', text)


def dax_references(expression):
    """DAX ifadesindeki referansları döndürür: [(tablo|None, ad), ...]"""
    code = strip_dax(expression)
    refs = []
    spans = []
    for match in _QUALIFIED.finditer(code):
        table = (match.group(1) or match.group(2)).replace("''", "'")
        refs.append((table, match.group(3)))
        spans.append(match.span())
    for match in _BRACKET.finditer(code):
        start = match.start()
        if any(a <= start < b for a, b in spans):
            continue
        refs.append((None, match.group(1)))
    return refs


def _key(name):
    # DAX büyük/küçük harf duyarsız
    return (name or '').strip().lower()


class UsageAnalysis:
    def __init__(self, metadata):
        self.metadata = metadata
        self.auto_tables = {t['name'] for t in metadata['tables'] if t['is_auto_date_table']}
        self.tables = [t for t in metadata['tables'] if t['name'] not in self.auto_tables]

        self.columns = {}      # (tablo_key, kolon_key) -> (tablo, kolon dict)
        self.measures = {}     # measure_key -> measure dict
        self.table_names = {}  # tablo_key -> gerçek ad
        for table in self.tables:
            self.table_names[_key(table['name'])] = table['name']
            for col in table['cols']:
                if col.get('kind') == 'rowNumber':
                    continue  # Power BI'ın iç sistem kolonu
                self.columns[(_key(table['name']), _key(col['name']))] = (table['name'], col)
            for measure in table.get('measures', []):
                self.measures[_key(measure['name'])] = measure

        self.used_columns = set()
        self.used_measures = set()
        self.reasons = {}
        self._run()

    # ---------------------------------------------------------------- çözümleme
    def _resolve(self, table, name, context_table=None):
        """Bir DAX/rapor referansını ('col', anahtar) veya ('measure', anahtar) olarak çözer."""
        name_key = _key(name)
        if table is not None:
            table_key = _key(table)
            if (table_key, name_key) in self.columns:
                return ('col', (table_key, name_key))
            if name_key in self.measures:
                return ('measure', name_key)
            return None
        if name_key in self.measures:
            return ('measure', name_key)
        if context_table is not None and (_key(context_table), name_key) in self.columns:
            return ('col', (_key(context_table), name_key))
        return None

    def _mark(self, resolved, reason, queue):
        if resolved is None:
            return
        kind, key = resolved
        target = self.used_columns if kind == 'col' else self.used_measures
        if key in target:
            return
        target.add(key)
        self.reasons[(kind, key)] = reason
        queue.append(resolved)

    # --------------------------------------------------------------- analiz
    def _run(self):
        queue = []
        md = self.metadata

        # 1) Rapor: görseller ve filtreler
        for table, field, kind in md.get('report_layout', {}).get('field_refs', []):
            if table in self.auto_tables:
                continue
            self._mark(self._resolve(table, field), 'rapor', queue)

        # 2) İlişki anahtarları (otomatik tarih ilişkileri parser'da ayıklandı)
        for rel in md.get('rels', []):
            self._mark(self._resolve(rel['from_table'], rel['from_col']), 'ilişki', queue)
            self._mark(self._resolve(rel['to_table'], rel['to_col']), 'ilişki', queue)

        # 3) RLS filtreleri ve calculated table ifadeleri
        for role in md.get('roles', []):
            for flt in role['filters']:
                for t, n in dax_references(flt['expression']):
                    self._mark(self._resolve(t, n, flt['table']), 'rls', queue)
        for table in self.tables:
            if table.get('partition_source_type') == 'calculated':
                for part in table.get('partitions', []):
                    for t, n in dax_references(part['expression']):
                        self._mark(self._resolve(t, n), 'calculated table', queue)

        # 4) Zincirleme: kullanılan measure/calculated column'ların içindekiler
        while queue:
            kind, key = queue.pop()
            if kind == 'measure':
                measure = self.measures[key]
                for t, n in dax_references(measure.get('formula_full')):
                    self._mark(self._resolve(t, n, measure['table']), f"measure: {measure['name']}", queue)
            else:
                table_name, col = self.columns[key]
                if col.get('is_calculated') and col.get('expression'):
                    for t, n in dax_references(col['expression']):
                        self._mark(self._resolve(t, n, table_name), f"kolon: {col['name']}", queue)
                if col.get('sort_by_column'):
                    self._mark(self._resolve(table_name, col['sort_by_column']), 'sıralama', queue)

    # --------------------------------------------------------------- sonuçlar
    def unused_data_columns(self):
        out = []
        for (tk, ck), (table_name, col) in self.columns.items():
            if not col.get('is_calculated') and (tk, ck) not in self.used_columns:
                out.append(f"{table_name}[{col['name']}]")
        return out

    def unused_calculated_columns(self):
        out = []
        for (tk, ck), (table_name, col) in self.columns.items():
            if col.get('is_calculated') and (tk, ck) not in self.used_columns:
                out.append(f"{table_name}[{col['name']}]")
        return out

    def used_calculated_columns(self):
        out = []
        for (tk, ck), (table_name, col) in self.columns.items():
            if col.get('is_calculated') and (tk, ck) in self.used_columns:
                out.append((table_name, col))
        return out

    def unused_measures(self):
        return [f"{m['table']}[{m['name']}]" for k, m in self.measures.items() if k not in self.used_measures]

    def is_column_used(self, table, column):
        return (_key(table), _key(column)) in self.used_columns
