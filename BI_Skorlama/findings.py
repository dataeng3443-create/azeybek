#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Bulgu (finding) modeli ve puanlama tablosu.

Puanlama: her kategori alt kovalardan (bucket) oluşur. Her kova kendi
puanıyla başlar ve içindeki bulguların kesintileri kadar düşer (0'ın altına
inmez). Böylece tek bir alandaki sorunlar diğer alanların puanını yiyemez.
Ağırlıkları değiştirmek için sadece SCORE_MODEL'i düzenlemek yeterli.
"""

from dataclasses import dataclass, field

SEVERITY_ORDER = ['critical', 'high', 'medium', 'low', 'info']

SEVERITY_LABELS = {
    'critical': 'KRİTİK',
    'high': 'YÜKSEK',
    'medium': 'ORTA',
    'low': 'DÜŞÜK',
    'info': 'BİLGİ',
}

SEVERITY_ICONS = {
    'critical': '🔴',
    'high': '🟠',
    'medium': '🟡',
    'low': '🔵',
    'info': 'ℹ️',
}

# kategori -> (etiket, [(kova anahtarı, kova etiketi, puan), ...])
SCORE_MODEL = {
    'modeling': ('Veri Modellemesi', [
        ('star_schema', 'Star schema', 10),
        ('many_to_many', 'N-N ilişkiler', 8),
        ('bidirectional', 'Çift yönlü filtre', 8),
        ('relationship_design', 'Kardinalite ve aktif/pasif', 6),
        ('isolated', 'İlişkisiz tablolar', 4),
        ('calendar', 'Calendar dimension', 4),
    ]),
    'query': ('Sorgu + DAX + Veri Tipi', [
        ('sql', 'SQL sorguları', 8),
        ('columns', 'Veri tipi ve kullanılmayan kolonlar', 12),
        ('dax', 'DAX (measure ve calculated column)', 10),
    ]),
    'visualization': ('Görselleştirme', [
        ('density', 'Görsel yoğunluğu', 12),
        ('chart_fit', 'Grafik uygunluğu', 10),
        ('naming', 'İsimlendirme', 8),
    ]),
}

# Kurallardaki kesinti değerleri (örn. "SELECT * : -3") bu ölçeklere göre yazıldı.
# Gerçek kesinti = kural kesintisi × (kovanın geçerli puanı / ölçek). Böylece kova
# ağırlıkları değişse de bir hata kovanın hep aynı yüzdesine mal olur; ağırlık
# değiştirmek için sadece SCORE_MODEL'i düzenlemek yeterli.
PENALTY_SCALE = {
    'star_schema': 10, 'many_to_many': 8, 'bidirectional': 8, 'relationship_design': 5,
    'isolated': 5, 'calendar': 4,
    'sql': 10, 'columns': 15, 'dax': 15,
    'density': 10, 'naming': 5, 'chart_fit': 5,
}

CATEGORY_LABELS = {key: label for key, (label, _) in SCORE_MODEL.items()}
CATEGORY_MAX = {key: sum(points for _, _, points in buckets) for key, (_, buckets) in SCORE_MODEL.items()}
BUCKET_INFO = {
    bucket: (category, label, points)
    for category, (_, buckets) in SCORE_MODEL.items()
    for bucket, label, points in buckets
}


@dataclass
class Finding:
    category: str                      # modeling | query | visualization
    area: str                          # kısa alan etiketi (raporda rozet)
    severity: str                      # critical | high | medium | low | info
    title: str
    detail: str = ""
    evidence: list = field(default_factory=list)
    fix: str = ""
    penalty: float = 0.0
    bucket: str = None                 # SCORE_MODEL kovası; bilgi notlarında None

    @property
    def severity_label(self):
        return SEVERITY_LABELS.get(self.severity, self.severity.upper())

    @property
    def icon(self):
        return SEVERITY_ICONS.get(self.severity, '•')

    @property
    def bucket_label(self):
        return BUCKET_INFO[self.bucket][1] if self.bucket in BUCKET_INFO else self.area

    @property
    def sort_key(self):
        order = SEVERITY_ORDER.index(self.severity) if self.severity in SEVERITY_ORDER else len(SEVERITY_ORDER)
        return (order, -self.penalty)

    def as_dict(self):
        return {
            "category": self.category,
            "bucket": self.bucket,
            "area": self.area,
            "severity": self.severity,
            "title": self.title,
            "detail": self.detail,
            "evidence": list(self.evidence),
            "fix": self.fix,
            "penalty": round(self.penalty, 2),
        }


def capped_penalty(unit_penalty, count, cap):
    """Tek kuralın toplam puan etkisini sınırlar."""
    return min(cap, unit_penalty * count)


def sort_findings(findings):
    return sorted(findings, key=lambda f: f.sort_key)


def effective_weights(applicable=None):
    """Uygulanamayan kovaların puanını aynı kategorideki diğer kovalara orantılı dağıtır.

    Örnek (Sorgu + DAX + Veri Tipi = 30; SQL 8, Veri tipi 12, DAX 10):
      SQL kaynağı yok           -> Veri tipi 16,4, DAX 13,6
      SQL ve DAX yok            -> Veri tipi 30
      SQL var, DAX yok          -> SQL 12, Veri tipi 18
    """
    applicable = applicable or {}
    weights = {}
    for category, (_, buckets) in SCORE_MODEL.items():
        category_total = sum(points for _, _, points in buckets)
        active_total = sum(points for key, _, points in buckets if applicable.get(key, True))
        for key, _, points in buckets:
            if applicable.get(key, True) and active_total:
                weights[key] = points * category_total / active_total
            else:
                weights[key] = 0.0
    return weights


def penalty_factor(bucket, weights):
    """Kural kesintisini gerçek puana çeviren çarpan (kova ağırlığı / kesinti ölçeği)."""
    scale = PENALTY_SCALE.get(bucket)
    if not scale:
        return 0.0
    return weights.get(bucket, 0.0) / scale


def compute_breakdown(findings, applicable=None, scope_notes=None):
    """Kova ve kategori puanlarını hesaplar.

    Bulguların penalty değeri gerçek puandır (analizör ölçeklemeyi bulguyu üretirken
    yapar), bu yüzden kova puanı = geçerli ağırlık - toplam kesinti (en az 0).

    Dönüş: {kategori: {"label", "score", "max", "buckets": [
             {"key","label","score","max","lost","base_max","applicable","note"}]}}
    """
    applicable = applicable or {}
    scope_notes = scope_notes or {}
    weights = effective_weights(applicable)
    lost = {}
    for finding in findings:
        if finding.bucket in BUCKET_INFO and finding.penalty > 0:
            lost[finding.bucket] = lost.get(finding.bucket, 0.0) + finding.penalty

    breakdown = {}
    for category, (label, buckets) in SCORE_MODEL.items():
        rows = []
        for key, bucket_label, points in buckets:
            weight = weights[key]
            is_applicable = applicable.get(key, True)
            score = max(0.0, weight - lost.get(key, 0.0)) if is_applicable else 0.0
            rows.append({
                "key": key,
                "label": bucket_label,
                "score": round(score, 1),
                "max": round(weight, 1),
                "lost": round(weight - score, 1),
                "base_max": points,
                "applicable": is_applicable,
                "note": None if is_applicable else scope_notes.get(key, "Uygulanmadı"),
            })
        breakdown[category] = {
            "label": label,
            "score": round(sum(r["score"] for r in rows), 1),
            "max": round(sum(r['max'] for r in rows), 1),
            "buckets": rows,
        }
    return breakdown
