"""Design tokens and the formatting rules every mode applies to Power BI visuals.

Only presentation properties appear here. Each (group, property) pair that a
rule can write is also listed in FORMAT_VC / FORMAT_OBJ, which the verifiers use
as the allowlist: anything else changing in a visual is rejected.
"""
from __future__ import annotations

import colorsys
import secrets

import designer as core

PALETTES = {
    "cobalt": dict(background="#F1F4FA", surface="#FFFFFF", text="#17243B", muted="#52627A", border="#E0E7F1", header="#EBF0F8", accent="#365FE8", secondary="#177D82", banner="#17243B", banner_text="#FFFFFF"),
    "teal": dict(background="#EEF4F5", surface="#FFFFFF", text="#17333B", muted="#526971", border="#DCE7E9", header="#EAF2F3", accent="#117F85", secondary="#4865CE", banner="#17333B", banner_text="#FFFFFF"),
    "violet": dict(background="#F3F3FA", surface="#FFFFFF", text="#26233F", muted="#625E79", border="#E4E2EF", header="#F0EEF8", accent="#6D50C9", secondary="#286EAE", banner="#26233F", banner_text="#FFFFFF"),
    "midnight": dict(background="#0E1625", surface="#182438", text="#F3F6FC", muted="#B2C2D8", border="#30425E", header="#22334D", accent="#8CA9FF", secondary="#5CD3CD", banner="#233656", banner_text="#FFFFFF"),
}

CARTESIAN = {"barChart", "columnChart", "clusteredBarChart", "clusteredColumnChart", "lineChart", "areaChart",
             "stackedAreaChart", "hundredPercentStackedColumnChart", "hundredPercentStackedBarChart",
             "lineClusteredColumnComboChart", "lineStackedColumnComboChart", "waterfallChart", "scatterChart"}
ROUND = {"pieChart", "donutChart"}
TABLES = {"tableEx", "pivotTable"}
KPI_TYPES = {"card", "multiRowCard", "kpi", "gauge"}

FORMAT_VC = {("background", "show"), ("background", "color"), ("background", "transparency"),
             ("border", "show"), ("border", "color"), ("border", "radius"),
             ("title", "show"), ("title", "text"), ("title", "bold"), ("title", "fontColor"),
             ("title", "fontFamily"), ("title", "fontSize")}
FORMAT_OBJ = {("categoryAxis", "labelColor"), ("categoryAxis", "fontSize"),
              ("valueAxis", "labelColor"), ("valueAxis", "fontSize"), ("valueAxis", "gridlineColor"),
              ("legend", "labelColor"), ("legend", "fontSize"), ("dataPoint", "defaultColor"),
              ("labels", "color"), ("labels", "fontSize"), ("categoryLabels", "color"), ("categoryLabels", "show"),
              ("grid", "textSize"), ("columnHeaders", "fontColor"), ("columnHeaders", "backColor"),
              ("columnHeaders", "fontFamily"), ("values", "fontColorPrimary"), ("values", "backColorPrimary"),
              ("items", "fontColor"), ("items", "textSize"), ("header", "fontColor")}
PAGE_OBJ = {("background", "color"), ("background", "transparency"), ("outspace", "color")}
TEXT_STYLE = {"fontFamily", "fontSize", "fontWeight", "color"}


# ---------------------------------------------------------------- colours
def rgb(value):
    return tuple(int(value[i:i + 2], 16) for i in (1, 3, 5))


def hex_color(channels):
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in channels)


def mix(a, b, t):
    return hex_color([x + (y - x) * t for x, y in zip(rgb(a), rgb(b))])


def contrast(a, b):
    la, lb = sorted([core.luminance(a), core.luminance(b)])
    return (lb + .05) / (la + .05)


def readable(color, backgrounds, ratio=4.5):
    """Move a colour toward black or white until it reads on every background."""
    dark = sum(core.luminance(b) for b in backgrounds) / len(backgrounds) > .35
    target = "#000000" if dark else "#FFFFFF"
    candidate = color
    for step in range(21):
        candidate = mix(color, target, step / 20)
        if min(contrast(candidate, b) for b in backgrounds) >= ratio:
            return candidate
    return target


def hue(color):
    r, g, b = (c / 255 for c in rgb(color))
    return colorsys.rgb_to_hsv(r, g, b)


def nearest_palette(accent):
    h, s, v = hue(accent)
    best, distance = "cobalt", 9
    for name, palette in PALETTES.items():
        ph = hue(palette["accent"])[0]
        d = min(abs(h - ph), 1 - abs(h - ph))
        if d < distance:
            best, distance = name, d
    return best


def build_style(colors, font="Segoe UI"):
    """Complete a contrast-checked token set from (possibly partial) colours."""
    c = dict(PALETTES["cobalt"])
    c.update({k: v for k, v in colors.items() if isinstance(v, str) and len(v) == 7 and v.startswith("#")})
    dark = core.luminance(c["background"]) < .2
    c["header"] = colors.get("header") or mix(c["surface"], c["accent"], .08)
    c["text"] = readable(c["text"], [c["background"], c["surface"], c["header"]], 7)
    c["muted"] = readable(c["muted"], [c["background"], c["surface"], c["header"]], 4.5)
    c["border"] = colors.get("border") or mix(c["surface"], c["text"], .14 if dark else .1)
    c["banner_text"] = readable(c.get("banner_text") or ("#FFFFFF" if core.luminance(c["banner"]) < .4 else c["text"]), [c["banner"]], 4.5)
    for key in ("accent", "secondary"):
        # Data colours need 3:1 against the card surface (WCAG non-text contrast).
        c[key] = readable(c[key], [c["surface"]], 3)
    return {**{k: c[k] for k in ("background", "surface", "text", "muted", "border", "header", "accent",
                                 "secondary", "banner", "banner_text")},
            "font": font, "title_size": 13, "body_size": 10, "value_size": 24, "radius": 10, "dark": dark}


def palette_style(name):
    return build_style(PALETTES.get(name, PALETTES["cobalt"]))


# ---------------------------------------------------------------- rules
def visual_rules(kind, style, *, title=None, priority=2, color_editable=False, show_title=True):
    """(vcObjects rules, objects rules) for one visual. Values are PBI expressions."""
    lit, col = core.literal, core.color
    vc = [("background", "show", lit(True)), ("background", "color", col(style["surface"])),
          ("background", "transparency", lit(0)),
          ("border", "show", lit(True)), ("border", "color", col(style["border"])), ("border", "radius", lit(style["radius"])),
          ("title", "fontColor", col(style["text"])), ("title", "fontFamily", lit(style["font"])),
          ("title", "fontSize", lit(style["title_size"]))]
    if title:
        vc += [("title", "text", lit(title)), ("title", "show", lit(show_title)), ("title", "bold", lit(True))]
    objects = []
    if kind in CARTESIAN:
        for group in ("categoryAxis", "valueAxis"):
            objects += [(group, "labelColor", col(style["muted"])), (group, "fontSize", lit(style["body_size"]))]
        objects += [("valueAxis", "gridlineColor", col(style["border"])),
                    ("legend", "labelColor", col(style["muted"])), ("legend", "fontSize", lit(style["body_size"]))]
        if color_editable:
            objects.append(("dataPoint", "defaultColor", col(style["accent"] if priority == 1 or style.get("mono") else style["secondary"])))
    elif kind in ROUND:
        objects += [("legend", "labelColor", col(style["muted"])), ("legend", "fontSize", lit(style["body_size"])),
                    ("labels", "color", col(style["text"]))]
    elif kind == "card":
        objects += [("labels", "color", col(style["text"])), ("labels", "fontSize", lit(style["value_size"])),
                    ("categoryLabels", "color", col(style["muted"]))]
    elif kind in TABLES:
        objects += [("grid", "textSize", lit(style["body_size"])),
                    ("columnHeaders", "fontColor", col(style["text"])), ("columnHeaders", "backColor", col(style["header"])),
                    ("columnHeaders", "fontFamily", lit(style["font"])),
                    ("values", "fontColorPrimary", col(style["text"])), ("values", "backColorPrimary", col(style["surface"]))]
    elif kind == "slicer":
        objects += [("items", "fontColor", col(style["text"])), ("items", "textSize", lit(style["body_size"])),
                    ("header", "fontColor", col(style["text"]))]
    return vc, objects


def banner_rules(style):
    lit, col = core.literal, core.color
    return [("background", "show", lit(True)), ("background", "color", col(style["banner"])),
            ("background", "transparency", lit(0)), ("border", "show", lit(False))]


def banner_text_style(style, size="22pt"):
    return {"fontFamily": style["font"], "fontSize": size, "fontWeight": "bold", "color": style["banner_text"]}


def new_name():
    return secrets.token_hex(10)


def textbox(text, rect, z, style):
    """A new title textbox (presentation only: no query, filters or bindings)."""
    position = {"x": rect["x"], "y": rect["y"], "z": z, "width": rect["width"], "height": rect["height"]}
    vc = {}
    for group, prop, value in banner_rules(style):
        vc.setdefault(group, [{"properties": {}}])[0]["properties"][prop] = value
    config = {"name": new_name(), "layouts": [{"id": 0, "position": position}],
              "singleVisual": {"visualType": "textbox", "drillFilterOtherVisuals": True,
                               "objects": {"general": [{"properties": {"paragraphs": [
                                   {"textRuns": [{"value": text, "textStyle": banner_text_style(style)}],
                                    "horizontalTextAlignment": "left"}]}}]},
                               "vcObjects": vc}}
    return {**position, "config": config}
