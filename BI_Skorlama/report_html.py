#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HTML rapor üretimi.

Analiz mantığından ayrı tutuldu: `build_html_report()` sadece hazır skorları,
bulguları ve (varsa) AI yorumunu alıp sayfayı döndürür.
"""

import html
import json
import re
from datetime import datetime

from findings import sort_findings

CSS = """
:root {
    --bg: #07111f;
    --panel: rgba(12, 20, 35, 0.78);
    --panel-2: rgba(17, 28, 48, 0.9);
    --border: rgba(255,255,255,0.08);
    --text: #e5eefc;
    --muted: #9bb0d0;
    --good: #2ecc71;
    --warning: #f39c12;
    --critical: #ff5d5d;
    --accent: #7c5cff;
    --accent-2: #32d3ff;
}
* { box-sizing: border-box; }
body {
    margin: 0;
    font-family: Inter, "Segoe UI", system-ui, -apple-system, sans-serif;
    color: var(--text);
    background:
        radial-gradient(circle at top left, rgba(124,92,255,0.3), transparent 30%),
        radial-gradient(circle at top right, rgba(50,211,255,0.18), transparent 25%),
        linear-gradient(180deg, #040810 0%, #091423 45%, #040810 100%);
    min-height: 100vh;
    padding: 28px;
}
.shell { max-width: 1380px; margin: 0 auto; }
.hero {
    position: relative;
    overflow: hidden;
    background: linear-gradient(135deg, rgba(124,92,255,0.2), rgba(50,211,255,0.18));
    border: 1px solid var(--border);
    border-radius: 28px;
    padding: 34px;
    box-shadow: 0 24px 80px rgba(0,0,0,0.35);
}
.hero-top { display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; flex-wrap: wrap; }
.title { font-size: 2.3rem; font-weight: 800; letter-spacing: -0.03em; margin: 0 0 8px 0; }
.subtitle { color: var(--muted); margin: 0; max-width: 760px; word-break: break-all; }
.status-pill {
    padding: 10px 16px; border-radius: 999px; font-weight: 700; display: inline-flex;
    align-items: center; gap: 10px; border: 1px solid rgba(255,255,255,0.12);
    background: rgba(255,255,255,0.06);
}
.hero-score { margin-top: 26px; display: grid; grid-template-columns: 240px 1fr; gap: 22px; align-items: center; }
.score-ring {
    width: 210px; height: 210px; border-radius: 50%; display: grid; place-items: center;
    box-shadow: inset 0 0 0 18px rgba(255,255,255,0.05);
}
.score-ring-inner { width: 160px; height: 160px; border-radius: 50%; background: rgba(6,11,21,0.95); display: grid; place-items: center; text-align: center; }
.score-value { font-size: 3rem; font-weight: 900; line-height: 1; }
.score-label { color: var(--muted); font-size: 0.95rem; margin-top: 6px; }
.grid { display: grid; gap: 18px; }
.cards { grid-template-columns: repeat(4, minmax(0, 1fr)); margin: 24px 0; }
.card {
    background: var(--panel); border: 1px solid var(--border); border-radius: 22px; padding: 20px;
    box-shadow: 0 14px 40px rgba(0,0,0,0.25);
}
.card h3 { margin: 0 0 10px 0; font-size: 1.02rem; color: #f2f6ff; }
.metric { font-size: 2rem; font-weight: 800; margin: 10px 0; }
.muted { color: var(--muted); }
.bar { height: 12px; border-radius: 999px; background: rgba(255,255,255,0.08); overflow: hidden; margin-top: 12px; }
.fill { height: 100%; border-radius: inherit; }
.card.good .metric { color: var(--good); }
.card.warning .metric { color: var(--warning); }
.card.critical .metric { color: var(--critical); }
.section { margin-top: 24px; }
.section-title { font-size: 1.3rem; margin: 0 0 14px 0; letter-spacing: -0.01em; }
.section-sub { color: var(--muted); margin: -6px 0 16px 0; font-size: 0.92rem; }
.two-col { display: grid; grid-template-columns: 1.15fr 0.85fr; gap: 18px; align-items: start; }
.finding {
    padding: 16px; border-radius: 16px; background: rgba(255,255,255,0.05);
    border: 1px solid rgba(255,255,255,0.05); margin-bottom: 12px; border-left: 4px solid var(--muted);
}
.finding.critical { border-left-color: var(--critical); }
.finding.high { border-left-color: #ff9f43; }
.finding.medium { border-left-color: var(--warning); }
.finding.low { border-left-color: var(--accent-2); }
.finding.info { border-left-color: rgba(255,255,255,0.25); }
.finding-head { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; margin-bottom: 8px; }
.finding-title { font-weight: 700; }
.badge {
    font-size: 0.7rem; font-weight: 800; letter-spacing: 0.08em; text-transform: uppercase;
    padding: 5px 9px; border-radius: 999px; background: rgba(255,255,255,0.08); white-space: nowrap;
}
.badge.critical { background: rgba(255,93,93,0.2); color: #ffc9c9; }
.badge.high { background: rgba(255,159,67,0.2); color: #ffdfc0; }
.badge.medium { background: rgba(243,156,18,0.18); color: #ffe6bb; }
.badge.low { background: rgba(50,211,255,0.16); color: #c7f1ff; }
.penalty { margin-left: auto; font-size: 0.82rem; color: var(--muted); }
.finding-detail { color: #d4e2f7; font-size: 0.93rem; }
.finding-fix { margin-top: 10px; padding: 10px 12px; border-radius: 12px; background: rgba(50,211,255,0.08); font-size: 0.9rem; }
.finding-fix b { color: var(--accent-2); }
.evidence { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.evidence code { background: rgba(0,0,0,0.35); padding: 4px 8px; border-radius: 8px; font-size: 0.8rem; color: #cfe3ff; }
.chips { display: flex; flex-wrap: wrap; gap: 8px; margin-top: 12px; }
.chip { padding: 7px 11px; border-radius: 999px; background: rgba(255,255,255,0.08); color: #dce8ff; font-size: 0.82rem; }
.pages { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.page-card { background: var(--panel-2); border: 1px solid var(--border); border-radius: 18px; padding: 18px; }
.page-title { font-weight: 800; font-size: 1.02rem; margin-bottom: 6px; }
.page-meta { color: var(--muted); font-size: 0.9rem; }
.checklist { display: grid; gap: 10px; }
.check { display: flex; gap: 12px; align-items: center; padding: 12px 14px; border-radius: 14px; background: rgba(255,255,255,0.05); }
.check::before { content: "\\2610"; color: var(--accent-2); font-size: 1.05rem; }
.ai-body { font-size: 0.95rem; line-height: 1.6; }
.ai-body h3 { margin: 18px 0 8px; font-size: 1.05rem; color: var(--accent-2); }
.ai-body ul { margin: 8px 0 8px 18px; padding: 0; }
.ai-body li { margin-bottom: 6px; }
.ai-body pre { background: rgba(0,0,0,0.4); padding: 12px 14px; border-radius: 12px; overflow-x: auto; font-size: 0.84rem; }
.ai-off { color: var(--muted); font-size: 0.92rem; }
.ai-warning { margin: 0 0 16px; padding: 12px 14px; border-radius: 12px; background: rgba(243,156,18,0.12); border: 1px solid rgba(243,156,18,0.35); color: #ffe6bb; font-size: 0.92rem; }
.app-nav { display: flex; justify-content: space-between; align-items: center; gap: 12px; margin-bottom: 18px; flex-wrap: wrap; }
.app-nav a { color: var(--text); text-decoration: none; padding: 10px 16px; border-radius: 12px; border: 1px solid var(--border); background: rgba(255,255,255,0.05); font-weight: 600; }
.app-nav a:hover { background: rgba(255,255,255,0.1); }
.app-nav a:focus-visible { outline: 2px solid var(--accent-2); outline-offset: 2px; }
.app-nav .muted { font-size: 0.9rem; }
@media print { .app-nav { display: none; } }
.breakdown { grid-template-columns: repeat(3, minmax(0, 1fr)); }
.bucket-title { display: flex; justify-content: space-between; gap: 8px; margin-bottom: 14px !important; }
.bucket { margin-bottom: 12px; }
.bucket.skipped { opacity: 0.75; }
.bucket-head { display: flex; justify-content: space-between; gap: 10px; font-size: 0.9rem; }
.bucket-head b { font-variant-numeric: tabular-nums; white-space: nowrap; }
.bar.thin { height: 7px; margin-top: 6px; }
.good-fill { background: var(--good); }
.warning-fill { background: var(--warning); }
.critical-fill { background: var(--critical); }
b.good, .verdict.good { color: var(--good); }
b.warning, .verdict.warning { color: var(--warning); }
b.critical, .verdict.critical { color: var(--critical); }
.table-wrap { overflow-x: auto; }
table.reviews { width: 100%; border-collapse: collapse; font-size: 0.92rem; }
table.reviews th { text-align: left; color: var(--muted); font-weight: 600; padding: 8px 10px; border-bottom: 1px solid var(--border); }
table.reviews td { padding: 10px; border-bottom: 1px solid var(--border); vertical-align: top; }
.verdict { font-weight: 700; }
.review-note { margin-top: 6px; font-size: 0.86rem; }
.small { font-size: 0.82rem; }
.footer { margin: 22px 0 6px; text-align: center; color: var(--muted); font-size: 0.9rem; }
@media (max-width: 1100px) {
    .cards, .two-col, .pages, .hero-score, .breakdown { grid-template-columns: 1fr; }
    .score-ring { margin: 0 auto; }
}
.report-actions { display: flex; flex-direction: column; align-items: flex-end; gap: 10px; }
.pdf-btn {
    appearance: none; cursor: pointer; font: inherit; font-weight: 700;
    padding: 10px 18px; border-radius: 12px; border: 0; background: var(--accent-2); color: #04121f;
}
.pdf-btn:hover { filter: brightness(1.08); }
.pdf-btn:focus-visible { outline: 2px solid #fff; outline-offset: 3px; }

/* ---------- PDF / yazdırma: açık tema, A4, kartlar sayfa arasında bölünmez ---------- */
@page { size: A4; margin: 12mm; }
@media print {
    :root {
        --panel: #ffffff; --panel-2: #ffffff; --border: #d9dee7; --text: #14181f; --muted: #5b6575;
        --good: #1e8e4f; --warning: #b86e00; --critical: #c62828; --accent-2: #0b7fab;
    }
    html, body { background: #ffffff !important; }
    body { padding: 0; font-size: 10.5pt; color: var(--text); -webkit-print-color-adjust: exact; print-color-adjust: exact; }
    .shell { max-width: none; }
    .app-nav, .pdf-btn { display: none !important; }
    .hero { background: #f3f6fa; box-shadow: none; border-radius: 12px; padding: 18px; }
    .card, .page-card { box-shadow: none; border-radius: 10px; }
    .card h3 { color: var(--text); }
    .title { font-size: 20pt; }
    .hero-score { grid-template-columns: 150px 1fr; margin-top: 14px; }
    .score-ring { width: 140px; height: 140px; box-shadow: none; margin: 0; }
    .score-ring-inner { width: 104px; height: 104px; background: #ffffff; }
    .score-value { font-size: 24pt; }
    .cards { grid-template-columns: repeat(2, minmax(0, 1fr)); margin: 0; gap: 10px; }
    .metric { font-size: 16pt; margin: 4px 0; }
    .breakdown { grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; }
    .two-col, .pages { grid-template-columns: 1fr; }
    .bar { background: #e6eaf0; }
    .status-pill { border-color: var(--border); background: #ffffff; }
    .finding, .check { background: #fafbfc; border-color: var(--border); }
    .finding.info { border-left-color: #b0b8c4; }
    .finding-detail { color: var(--text); }
    .finding-fix { background: #eaf4f9; }
    .badge { background: #eef0f3; color: var(--text); }
    .badge.critical { background: #fde4e4; color: #9b1c1c; }
    .badge.high { background: #ffe9d6; color: #8a4b00; }
    .badge.medium { background: #fff3d6; color: #7a5400; }
    .badge.low { background: #dff3fb; color: #0b5b7a; }
    .evidence code { background: #eef0f3; color: #1d2633; }
    .chip { background: #eef0f3; color: var(--text); }
    .ai-body pre { background: #f4f6f9; color: var(--text); white-space: pre-wrap; }
    .ai-warning { background: #fff6e0; color: #6b4a00; border-color: #f0c36a; }
    .finding, .bucket, .check, .page-card, table.reviews tr, .ai-warning, .ai-body pre { break-inside: avoid; }
    .section-title { break-after: avoid; }
    .section { margin-top: 14px; }
    .table-wrap { overflow: visible; }
    .findings-section { break-before: page; margin-top: 0; }
    .bucket-title { font-size: 10pt; }
    .bucket-title .muted { white-space: nowrap; }
}
"""


def _fmt_score(value):
    """50.5 -> '50,5', 50.0 -> '50' (arayüzdeki gösterimle aynı)."""
    text = f"{value:.1f}".rstrip('0').rstrip('.')
    return text.replace('.', ',')


def esc(value):
    return html.escape(str(value), quote=True)


def score_variant(score, max_score):
    if max_score <= 0:
        return "critical"
    ratio = (score / max_score) * 100
    if ratio >= 80:
        return "good"
    if ratio >= 60:
        return "warning"
    return "critical"


def markdown_lite(text):
    """LLM çıktısındaki basit markdown'ı güvenli HTML'e çevirir."""
    if not text:
        return ""

    blocks = []
    for index, chunk in enumerate(re.split(r"```", text)):
        if index % 2 == 1:  # kod bloğu
            blocks.append(f"<pre>{esc(chunk.strip())}</pre>")
            continue

        html_lines = []
        in_list = False
        for raw_line in chunk.splitlines():
            line = raw_line.rstrip()
            if not line.strip():
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                continue

            heading = re.match(r"^\s*#{1,6}\s*(.+)$", line)
            bullet = re.match(r"^\s*(?:[-*•]|\d+[.)])\s+(.+)$", line)

            if heading:
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append(f"<h3>{_inline(heading.group(1))}</h3>")
            elif bullet:
                if not in_list:
                    html_lines.append("<ul>")
                    in_list = True
                html_lines.append(f"<li>{_inline(bullet.group(1))}</li>")
            else:
                if in_list:
                    html_lines.append("</ul>")
                    in_list = False
                html_lines.append(f"<p>{_inline(line.strip())}</p>")

        if in_list:
            html_lines.append("</ul>")
        blocks.append("\n".join(html_lines))

    return "\n".join(blocks)


def _inline(text):
    safe = esc(text)
    safe = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", safe)
    safe = re.sub(r"`(.+?)`", r"<code>\1</code>", safe)
    return safe


def _finding_html(finding):
    evidence = ""
    if finding.evidence:
        items = ''.join(f"<code>{esc(item)}</code>" for item in finding.evidence[:12])
        extra = ""
        if len(finding.evidence) > 12:
            extra = f"<code>+{len(finding.evidence) - 12} tane daha</code>"
        evidence = f"<div class='evidence'>{items}{extra}</div>"

    fix = ""
    if finding.fix:
        fix = f"<div class='finding-fix'><b>Düzeltme:</b> {esc(finding.fix)}</div>"

    penalty = ""
    if finding.penalty:
        penalty = f"<span class='penalty'>-{finding.penalty:g} puan</span>"

    return f"""<div class="finding {esc(finding.severity)}">
    <div class="finding-head">
        <span class="badge {esc(finding.severity)}">{esc(finding.severity_label)}</span>
        <span class="badge">{esc(finding.area)}</span>
        <span class="finding-title">{esc(finding.title)}</span>
        {penalty}
    </div>
    <div class="finding-detail">{esc(finding.detail)}</div>
    {evidence}
    {fix}
</div>"""


def build_html_report(
    pbit_file,
    metadata,
    findings,
    breakdown,
    total_score,
    status,
    description,
    checklist,
    visual_reviews=None,
    ai_commentary=None,
    ai_note=None,
    ai_warnings=None,
    nav_html=None,
):
    layout = metadata.get('report_layout', {}) or {}
    profile = metadata.get('profile', {}) or {}
    pages = layout.get('pages', []) or []
    visual_types = layout.get('visual_type_counts', {}) or {}

    summary_cards = [(data['label'], data['score'], data['max']) for data in breakdown.values()]
    summary_cards.append(("Genel Skor", total_score, sum(data['max'] for data in breakdown.values())))

    card_html = []
    for title, score, max_score in summary_cards:
        variant = score_variant(score, max_score)
        width = 0 if not max_score else (score / max_score) * 100
        head_color = {'good': '#32d3ff', 'warning': '#f39c12', 'critical': '#ff5d5d'}[variant]
        card_html.append(f"""<div class="card {variant}">
    <h3>{esc(title)}</h3>
    <div class="metric">{_fmt_score(score)}/{_fmt_score(max_score)}</div>
    <div class="muted">{width:.0f}% başarı</div>
    <div class="bar"><div class="fill" style="width: {width:.1f}%; background: linear-gradient(90deg, {head_color}, rgba(124,92,255,0.9));"></div></div>
</div>""")

    ordered = sort_findings(findings)
    scored_findings = [f for f in ordered if f.penalty > 0]
    info_findings = [f for f in ordered if f.penalty == 0]

    findings_html = ''.join(_finding_html(f) for f in scored_findings) or \
        "<div class='muted'>Puan kıran bir bulgu yok.</div>"
    info_html = ''.join(_finding_html(f) for f in info_findings) or \
        "<div class='muted'>Ek not yok.</div>"

    page_html = []
    for page in pages:
        chips = ''.join(
            f"<span class='chip'>{esc(v_type)}: {count}</span>"
            for v_type, count in (page.get('visual_types', {}) or {}).items()
        )
        page_html.append(f"""<div class='page-card'>
    <div class='page-title'>{esc(page.get('name', 'Sayfa'))}</div>
    <div class='page-meta'>{page.get('data_visual_count', 0)} veri görseli · {page.get('slicer_count', 0)} slicer</div>
    <div class='chips'>{chips}</div>
</div>""")

    role_chips = []
    for label, names in (
        ("Fact", profile.get('facts', [])),
        ("Dimension", profile.get('dimensions', [])),
        ("Bridge", profile.get('bridges', [])),
        ("İzole", profile.get('isolated', [])),
        ("Tarih dimension", profile.get('date_dimensions', [])),
        ("Otomatik tarih tablosu", profile.get('auto_date_tables', [])),
    ):
        if names:
            role_chips.append(f"<span class='chip'>{esc(label)}: {esc(', '.join(names))}</span>")
    role_chips_html = ''.join(role_chips) or "<span class='chip'>Rol tespit edilemedi</span>"

    breakdown_html = []
    for data in breakdown.values():
        rows = []
        for bucket in data['buckets']:
            if not bucket.get('applicable', True):
                rows.append(f"""<div class="bucket skipped">
    <div class="bucket-head"><span>{esc(bucket['label'])}</span><b class="muted">Uygulanmadı</b></div>
    <div class="muted small">{esc(bucket.get('note') or '')}</div>
</div>""")
                continue
            variant = score_variant(bucket['score'], bucket['max'])
            width = 0 if not bucket['max'] else bucket['score'] / bucket['max'] * 100
            rows.append(f"""<div class="bucket">
    <div class="bucket-head"><span>{esc(bucket['label'])}</span><b class="{variant}">{_fmt_score(bucket['score'])} / {_fmt_score(bucket['max'])}</b></div>
    <div class="bar thin"><div class="fill {variant}-fill" style="width:{width:.1f}%"></div></div>
</div>""")
        breakdown_html.append(f"""<div class="card">
    <h3 class="bucket-title">{esc(data['label'])} <span class="muted">{_fmt_score(data['score'])} / {_fmt_score(data['max'])}</span></h3>
    {''.join(rows)}
</div>""")

    verdict_labels = {'ok': ('Uygun', 'good'), 'suggest': ('Öneri', 'warning'), 'error': ('Uygun değil', 'critical')}
    review_rows = []
    for review in visual_reviews or []:
        if review.get('verdict') == 'skip':
            continue
        label, variant = verdict_labels.get(review['verdict'], ('-', 'muted'))
        notes = ''.join(
            f"<div class='review-note'>{esc(text)} <span class='muted'>{esc(rec)}</span></div>"
            for _, text, rec in review.get('issues', [])
        )
        review_rows.append(f"""<tr>
    <td>{esc(review['page'])}</td>
    <td>{esc(review['title']) + '<div class="muted small">' + esc(review['type_label']) + '</div>' if review.get('title') else esc(review['type_label'])}</td>
    <td class="small">{esc(review.get('field_summary', ''))}</td>
    <td><span class="verdict {variant}">{label}</span>{notes}</td>
</tr>""")
    reviews_html = (
        "<div class='table-wrap'><table class='reviews'><thead><tr><th>Sayfa</th><th>Görsel</th>"
        "<th>Alanlar (anlamı)</th><th>Sonuç</th></tr></thead><tbody>" + ''.join(review_rows) + "</tbody></table></div>"
        if review_rows else "<div class='muted'>Değerlendirilecek görsel bulunamadı.</div>"
    )

    checklist_html = ''.join(f"<div class='check'>{esc(item)}</div>" for item in checklist)

    if ai_commentary:
        warning_html = ""
        if ai_warnings:
            refs = ''.join(f"<code>{esc(ref)}</code>" for ref in ai_warnings)
            warning_html = (
                "<div class='ai-warning'><b>Kontrol edilmeli:</b> AI'nin önerdiği kodda modelde bulunmayan "
                f"alanlar geçiyor. Bu satırları uygulamadan önce gerçek kolon adlarıyla düzelt."
                f"<div class='evidence'>{refs}</div></div>"
            )
        ai_html = f"{warning_html}<div class='ai-body'>{markdown_lite(ai_commentary)}</div>"
    else:
        ai_html = f"<div class='ai-off'>{esc(ai_note or 'AI yorumu bu çalıştırmada üretilmedi.')}</div>"

    stem = re.sub(r'\.pbit$', '', str(pbit_file), flags=re.IGNORECASE)
    stem = re.sub(r'[\\/:*?"<>|]+', '_', stem).strip() or 'rapor'
    pdf_name_js = json.dumps(f"{stem} - Analiz Raporu", ensure_ascii=False).replace('<', '\\u003c')

    ring_style = (
        f"background: conic-gradient(var(--accent-2) {max(0, min(100, total_score)):.1f}%, "
        "rgba(255,255,255,0.08) 0);"
    )

    return f"""<!DOCTYPE html>
<html lang="tr">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Power BI Kapsamlı Analiz Raporu</title>
    <style>{CSS}</style>
</head>
<body>
    <div class="shell">
        {nav_html or ''}
        <section class="hero">
            <div class="hero-top">
                <div>
                    <h1 class="title">Power BI Kapsamlı Analiz Raporu</h1>
                    <p class="subtitle">{esc(pbit_file)} için kural tabanlı denetim{' + AI yorumu' if ai_commentary else ''}.</p>
                </div>
                <div class="report-actions">
                    <button type="button" class="pdf-btn" id="pdfButton" title="Raporu PDF olarak kaydet">PDF olarak indir</button>
                    <div class="status-pill">{esc(status)} <span class="muted">{esc(description)}</span></div>
                </div>
            </div>
            <div class="hero-score">
                <div class="score-ring" style="{ring_style}">
                    <div class="score-ring-inner">
                        <div>
                            <div class="score-value">{_fmt_score(total_score)}</div>
                            <div class="score-label">/100 Genel Skor</div>
                        </div>
                    </div>
                </div>
                <div>
                    <div class="grid cards">{''.join(card_html)}</div>
                </div>
            </div>
        </section>

        <section class="section">
            <h2 class="section-title">Puan Dağılımı</h2>
            <div class="grid breakdown">{''.join(breakdown_html)}</div>
        </section>

        <section class="section two-col findings-section">
            <div class="card">
                <h2 class="section-title">Puan Kıran Bulgular</h2>
                <p class="section-sub">{len(scored_findings)} bulgu, önem sırasına göre.</p>
                {findings_html}
            </div>
            <div class="card">
                <h2 class="section-title">Model Özeti</h2>
                <div class="checklist">
                    <div class="check">Tablo: {metadata.get('visible_table_count', 0)} görünür / {metadata.get('table_count', 0)} toplam</div>
                    <div class="check">İlişki: {metadata.get('rel_count', 0)}</div>
                    <div class="check">Measure: {metadata.get('measure_count', 0)}</div>
                    <div class="check">Kolon: {metadata.get('column_count', 0)}</div>
                    <div class="check">Sayfa: {layout.get('page_count', 0)} · Görsel: {layout.get('visual_count', 0)}</div>
                    <div class="check">Rol tespiti: {esc(profile.get('method', '-'))}</div>
                </div>
                <div class="chips" style="margin-top:16px;">{role_chips_html}</div>
                <div class="chips">{''.join(f"<span class='chip'>{esc(k)}: {v}</span>" for k, v in visual_types.items())}</div>
            </div>
        </section>

        <section class="section card">
            <h2 class="section-title">AI Yorumu ve Düzeltme Planı</h2>
            <p class="section-sub">Yorum yalnızca yukarıdaki kural bulgularına dayanır.</p>
            {ai_html}
        </section>

        <section class="section card">
            <h2 class="section-title">Bilgi Notları</h2>
            <p class="section-sub">Puan kırmayan gözlemler ve öneriler.</p>
            {info_html}
        </section>

        <section class="section card">
            <h2 class="section-title">Görsel Analizi</h2>
            <p class="section-sub">Her görselin alanları anlamına göre sınıflandırıldı ve görsel türüyle karşılaştırıldı. Sadece "Uygun değil" sonuçları puan kırar.</p>
            {reviews_html}
        </section>

        <section class="section card">
            <h2 class="section-title">Sayfa Görünümü</h2>
            <div class="pages">{''.join(page_html) if page_html else "<div class='muted'>Report/Layout verisi bulunamadı.</div>"}</div>
        </section>

        <section class="section card">
            <h2 class="section-title">Deployment Checklist</h2>
            <div class="checklist">{checklist_html}</div>
        </section>

        <script>
        (function () {{
            var button = document.getElementById('pdfButton');
            if (!button) return;
            button.addEventListener('click', function () {{
                var original = document.title;
                // Tarayıcı PDF dosyasına sayfa başlığını ad olarak verir
                document.title = {pdf_name_js};
                window.addEventListener('afterprint', function restore() {{
                    document.title = original;
                    window.removeEventListener('afterprint', restore);
                }});
                window.print();
            }});
        }})();
        </script>
        <div class="footer">Oluşturulma zamanı: {esc(datetime.now().strftime('%d.%m.%Y %H:%M:%S'))}</div>
    </div>
</body>
</html>"""
