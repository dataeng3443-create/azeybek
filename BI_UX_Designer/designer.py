"""Core PBIT adapter: package I/O, local model client (Ollama/Qwen) and safety gates.

Only visual properties are writable. The semantic model is copied byte-for-byte.
External PBIT editing is not a Microsoft-supported rendering API: Desktop QA is
explicitly outstanding even after every structural check passes.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import io
import json
import math
import os
from pathlib import Path, PurePosixPath
import re
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parent
MAX_EXPANDED = 150 * 1024 * 1024
MAX_LAYOUT = 12 * 1024 * 1024
NATIVE = {"tableEx", "pivotTable", "slicer", "card", "multiRowCard", "kpi",
          "lineChart", "areaChart", "stackedAreaChart", "columnChart", "barChart",
          "clusteredColumnChart", "clusteredBarChart", "hundredPercentStackedColumnChart",
          "hundredPercentStackedBarChart", "lineClusteredColumnComboChart",
          "lineStackedColumnComboChart", "pieChart", "donutChart", "scatterChart",
          "waterfallChart", "funnel", "gauge", "treemap"}
CHARTS = NATIVE - {"tableEx", "pivotTable", "slicer", "card", "multiRowCard", "kpi"}
COLOR = {"type": "string", "pattern": "^#[0-9A-Fa-f]{6}$"}


def obj(properties):
    return {"type": "object", "properties": properties, "required": list(properties), "additionalProperties": False}


STYLE_SCHEMA = obj({
    "background": COLOR, "surface": COLOR, "text": COLOR, "muted": COLOR,
    "border": COLOR, "header": COLOR,
    "font": {"type": "string", "enum": ["Segoe UI", "Arial"]},
    "title_size": {"type": "integer", "minimum": 14, "maximum": 20},
    "body_size": {"type": "integer", "minimum": 10, "maximum": 14},
    "radius": {"type": "integer", "minimum": 8, "maximum": 16},
    "reason": {"type": "string", "maxLength": 1000},
})


def strict_json(text):
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError("Yinelenen JSON alanı bulundu.")
            result[key] = value
        return result
    def invalid(value):
        raise ValueError("Geçersiz JSON sayısı: " + value)
    return json.loads(text, object_pairs_hook=pairs, parse_constant=invalid)


def validate(value, schema, path="plan"):
    kind = schema.get("type")
    if "enum" in schema and value not in schema["enum"]:
        raise ValueError(f"{path}: geçersiz seçenek {value!r}; izin verilenler: {schema['enum'][:30]}")
    if kind == "object":
        if not isinstance(value, dict) or set(value) != set(schema["required"]):
            raise ValueError(f"{path}: beklenmeyen veya eksik alan.")
        for key, field in schema["properties"].items():
            validate(value[key], field, path + "." + key)
    elif kind == "array":
        if not isinstance(value, list) or len(value) > schema.get("maxItems", 1000):
            raise ValueError(f"{path}: geçersiz liste.")
        for index, item in enumerate(value):
            validate(item, schema["items"], f"{path}[{index}]")
    elif kind == "string":
        if not isinstance(value, str) or len(value) > schema.get("maxLength", 5000):
            raise ValueError(f"{path}: geçersiz metin.")
        if schema.get("pattern") and not re.fullmatch(schema["pattern"], value):
            raise ValueError(f"{path}: geçersiz renk.")
    elif kind in {"integer", "number"}:
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
            raise ValueError(f"{path}: geçersiz sayı.")
        if kind == "integer" and not isinstance(value, int):
            raise ValueError(f"{path}: tam sayı gerekiyor.")
        if value < schema.get("minimum", -math.inf) or value > schema.get("maximum", math.inf):
            raise ValueError(f"{path}: sayı sınır dışında.")


def json_text(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def decode_layout(raw):
    for encoding, prefix in [("utf-16-le", b"\xff\xfe"), ("utf-16-be", b"\xfe\xff"), ("utf-8", b"\xef\xbb\xbf")]:
        if raw.startswith(prefix):
            return strict_json(raw[len(prefix):].decode(encoding)), encoding, prefix
    encoding = "utf-16-le" if raw[:80].count(b"\x00") > 10 else "utf-8"
    return strict_json(raw.decode(encoding)), encoding, b""


def read_package(path):
    try:
        raw = path.read_bytes()
        if len(raw) > 50 * 1024 * 1024:
            raise ValueError("Şablon 50 MB sınırını aşıyor.")
        with zipfile.ZipFile(io.BytesIO(raw)) as archive:
            entries = archive.infolist()
            names = [i.filename for i in entries]
            if len(entries) > 5000 or len(set(names)) != len(names):
                raise ValueError("Şablonda yinelenen veya çok fazla paket parçası var.")
            if sum(i.file_size for i in entries) > MAX_EXPANDED:
                raise ValueError("Açılmış şablon boyutu desteklenen sınırı aşıyor.")
            for entry in entries:
                p = PurePosixPath(entry.filename)
                if p.is_absolute() or ".." in p.parts or "\\" in entry.filename or entry.flag_bits & 1:
                    raise ValueError("Şifreli veya desteklenmeyen paket yapısı.")
            if "Report/Layout" not in names or "DataModelSchema" not in names:
                raise ValueError("Bu PBIT biçimi henüz desteklenmiyor. Report/Layout ve DataModelSchema içeren şablon gerekiyor.")
            if archive.getinfo("Report/Layout").file_size > MAX_LAYOUT:
                raise ValueError("Rapor düzeni desteklenen boyutu aşıyor.")
            if any("sensitivity" in n.lower() or n.lower().startswith("_xmlsignatures/") for n in names):
                raise ValueError("Etiketli veya imzalı şablonlar otomatik düzenlemeye uygun değil.")
            parts = {i.filename: archive.read(i) for i in entries}
            layout, encoding, prefix = decode_layout(parts["Report/Layout"])
            if not isinstance(layout, dict) or not isinstance(layout.get("sections"), list) or not layout["sections"]:
                raise ValueError("Şablonda desteklenen rapor sayfası bulunamadı.")
            if len(layout["sections"]) > 40:
                raise ValueError("İlk sürüm en fazla 40 sayfayı destekliyor.")
            return raw, entries, parts, archive.comment, layout, encoding, prefix
    except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError, KeyError) as exc:
        raise ValueError("Dosya geçerli ve desteklenen bir Power BI şablonu olarak okunamadı.") from exc


def literal(value):
    if isinstance(value, str):
        text = "'" + value.replace("'", "''") + "'"
    elif isinstance(value, bool):
        text = str(value).lower()
    else:
        text = str(value) + "D"
    return {"expr": {"Literal": {"Value": text}}}


def color(value):
    return {"solid": {"color": literal(value)}}


def luminance(hex_color):
    channels = [int(hex_color[i:i+2], 16) / 255 for i in (1, 3, 5)]
    channels = [x / 12.92 if x <= .04045 else ((x + .055) / 1.055) ** 2.4 for x in channels]
    return sum(c * w for c, w in zip(channels, (.2126, .7152, .0722)))


def validate_style(style):
    validate(style, STYLE_SCHEMA)
    for background in ("surface", "background", "header"):
        if luminance(style[background]) < .75:
            raise ValueError("Açık tema için daha açık yüzey renkleri gerekiyor.")
        for foreground in ("text", "muted"):
            a, b = sorted([luminance(style[foreground]), luminance(style[background])])
            if (b + .05) / (a + .05) < 4.5:
                raise ValueError("Metin ve yüzey renkleri yeterli kontrast sağlamıyor.")


DEFAULT_MODEL = "qwen3:8b"
OLLAMA_URL = os.environ.get("UX_OLLAMA_URL", "http://127.0.0.1:11434").rstrip("/")


def installed_models(timeout=5):
    """Names of the models installed in the local Ollama service."""
    with urllib.request.urlopen(OLLAMA_URL + "/api/tags", timeout=timeout) as response:
        return [m.get("name", "") for m in json.load(response).get("models", []) if isinstance(m, dict)]


def model_installed(model, names):
    return model in names or (":" not in model and model + ":latest" in names)


THINK_BLOCK = re.compile(r"<think>.*?</think>", re.S | re.I)


def model_json(text):
    """Extract the JSON object from a Qwen answer (thinking blocks / fences removed)."""
    text = THINK_BLOCK.sub("", text or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\s*|\s*```$", "", text).strip()
    if not text.startswith("{"):
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Model yanıtında JSON bulunamadı.")
        text = text[start:end + 1]
    return strict_json(text)


def ask_model(model, system, prompt, schema, checker=None, attempts=3, timeout=300):
    """Ask the local Ollama model (default qwen3:8b) for schema-constrained JSON.

    Only the local Ollama endpoint is used; nothing leaves this computer. Qwen3's
    thinking mode is disabled so the answer is the JSON object itself.
    """
    try:
        names = installed_models()
    except (urllib.error.URLError, TimeoutError, ConnectionError, OSError, ValueError) as exc:
        raise RuntimeError("Ollama'ya bağlanılamadı. Ollama uygulamasını açıp tekrar deneyin.") from exc
    if not model_installed(model, names):
        raise RuntimeError(f"{model} modeli Ollama'da bulunamadı. Terminalde 'ollama pull {model}' çalıştırın.")
    last_error, think = "", True
    attempt = 0
    while attempt < attempts:
        body = {"model": model, "system": system,
                "prompt": prompt + ("\nPrevious answer was rejected: " + last_error + " Return corrected JSON." if last_error else "") + "\n/no_think",
                "format": schema, "stream": False, "keep_alive": "10m",
                "options": {"temperature": 0 if attempt == 0 else 0.3, "num_ctx": 16384, "num_predict": 4096}}
        if think:
            body["think"] = False
        request = urllib.request.Request(OLLAMA_URL + "/api/generate", json_text(body).encode(), {"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                envelope = strict_json(response.read(4 * 1024 * 1024).decode())
        except urllib.error.HTTPError as exc:
            detail = exc.read(2000).decode(errors="replace")
            if think and exc.code == 400 and "think" in detail.lower():
                think = False          # older Ollama: retry without the field
                continue
            raise RuntimeError("Ollama isteği reddetti: " + detail[:300]) from exc
        except (urllib.error.URLError, TimeoutError, ConnectionError, OSError) as exc:
            raise RuntimeError("Model yanıt vermedi. Ollama'nın açık olduğundan emin olup tekrar deneyin.") from exc
        attempt += 1
        try:
            if envelope.get("done_reason") == "length":
                raise ValueError("Yanıt yarım kaldı; daha kısa yanıt ver.")
            result = model_json(envelope.get("response", ""))
            validate(result, schema)
            if checker:
                checker(result)
            return result
        except (ValueError, TypeError) as exc:
            last_error = str(exc)[:400]
    raise RuntimeError("Model geçerli bir tasarım planı üretemedi: " + last_error)


def parsed_config(owner):
    config = owner.get("config", "{}")
    if not isinstance(config, str):
        raise ValueError("Desteklenmeyen görsel yapılandırması.")
    value = strict_json(config)
    if not isinstance(value, dict):
        raise ValueError("Geçersiz görsel yapılandırması.")
    return value


def inspect(layout):
    result = []
    report_config = parsed_config(layout)
    bookmarks = bool(report_config.get("bookmarks"))
    for si, section in enumerate(layout["sections"]):
        config = parsed_config(section)
        visuals = section.get("visualContainers", [])
        if not isinstance(visuals, list) or len(visuals) > 100:
            raise ValueError("Sayfa başına en fazla 100 görsel destekleniyor.")
        page = {"page": si, "name": str(section.get("displayName", ""))[:120],
                "width": section.get("width"), "height": section.get("height"), "visuals": []}
        for key in ("width", "height"):
            if isinstance(page[key], bool) or not isinstance(page[key], (int, float)) or not 100 <= page[key] <= 20000:
                raise ValueError("Geçersiz sayfa boyutu.")
        complex_page = bookmarks or bool(config.get("visibility")) or any(
            parsed_config(v).get("singleVisualGroup") or parsed_config(v).get("parentGroupName") for v in visuals)
        for vi, visual in enumerate(visuals):
            vc = parsed_config(visual)
            sv = vc.get("singleVisual", {})
            kind = sv.get("visualType", "unknown")
            bounds = {k: visual.get(k) for k in ("x", "y", "width", "height")}
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in bounds.values()):
                raise ValueError("Geçersiz görsel konumu.")
            layouts = vc.get("layouts", [])
            desktop = [item for item in layouts if item.get("id") == 0 and isinstance(item.get("position"), dict)]
            supported = kind in NATIVE and not complex_page and not vc.get("parentGroupName")
            title = ""
            try:
                title = sv["vcObjects"]["title"][0]["properties"]["text"]["expr"]["Literal"]["Value"]
            except (KeyError, IndexError, TypeError):
                pass
            # Only field names and layout metadata enter the local model; no rows,
            # DAX, Power Query, connection strings or filter values are included.
            fields = [p.get("queryRef", "") for values in sv.get("projections", {}).values() for p in values if isinstance(p, dict)]
            page["visuals"].append({"visual": vi, "type": kind, "title": str(title)[:160],
                                    "fields": fields[:12], **bounds,
                                    "editable": supported, "movable": supported and len(desktop) == 1})
        result.append(page)
    return result


def rect_overlap(a, b):
    return max(0, min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"])) * max(0, min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"]))


def plan_schema(pages):
    return obj({"placements": {"type": "array", "maxItems": sum(len(p["visuals"]) for p in pages), "items": obj({
        "page": {"type": "integer", "minimum": 0, "maximum": max(p["page"] for p in pages)},
        "visual": {"type": "integer", "minimum": 0, "maximum": 99},
        "x": {"type": "number", "minimum": 0}, "y": {"type": "number", "minimum": 0},
        "width": {"type": "number", "minimum": 40}, "height": {"type": "number", "minimum": 40},
    })}})


BOUNDS = ("x", "y", "width", "height")


def check_plan_identity(plan, pages):
    """Never repair ambiguous IDs, missing visuals, or malformed model output."""
    validate(plan, plan_schema(pages))
    expected = {(p["page"], v["visual"]) for p in pages for v in p["visuals"] if v["movable"]}
    changes = {(v["page"], v["visual"]): v for v in plan["placements"]}
    if len(changes) != len(plan["placements"]) or set(changes) != expected:
        raise ValueError("Her taşınabilir görsel tam bir kez listelenmeli, diğerleri listelenmemeli.")


def check_plan(plan, pages):
    check_plan_identity(plan, pages)
    changes = {(v["page"], v["visual"]): v for v in plan["placements"]}
    for page in pages:
        before = page["visuals"]
        after = [changes.get((page["page"], v["visual"]), v) for v in before]
        for old, new in zip(before, after):
            # Preserve existing geometry exactly when a safe new layout cannot
            # be found. An existing overflow is not an introduced overflow.
            if all(new[k] == old[k] for k in BOUNDS):
                continue
            if new["x"] < 0 or new["y"] < 0 or new["x"] + new["width"] > page["width"] or new["y"] + new["height"] > page["height"]:
                raise ValueError("Görsel sayfa dışına taşıyor.")
            # Shrinking can clip labels or remove visible rows, so never reduce
            # usable area in this initial adapter.
            if new["width"] < old["width"] or new["height"] < old["height"]:
                raise ValueError("Görsel genişliği ve yüksekliği mevcut boyutlardan küçük olamaz.")
        for i in range(len(before)):
            for j in range(i + 1, len(before)):
                if rect_overlap(after[i], after[j]) > rect_overlap(before[i], before[j]) + 1:
                    raise ValueError("Görseller arasında yeni örtüşme oluşuyor.")


def fit_bounds(proposal, original, page):
    """Fit the proposed rectangle without ever shrinking the original visual."""
    fitted = {"page": page["page"], "visual": original["visual"]}
    for position, size in (("x", "width"), ("y", "height")):
        if original[size] > page[size]:
            # A canvas-sized minimum cannot be honored; preserve this visual.
            return {**fitted, **{key: original[key] for key in BOUNDS}}
        fitted[size] = min(page[size], max(original[size], proposal[size]))
        maximum = page[size] - fitted[size]
        fitted[position] = min(maximum, max(0, proposal[position]))
        # Subtraction followed by addition can round just beyond the edge.
        if fitted[position] + fitted[size] > page[size]:
            fitted[position] = math.nextafter(fitted[position], -math.inf)
    return fitted


def normalize_plan(plan, pages):
    """Repair geometry deterministically, then run the unchanged safety gates.

    First fit proposals to the canvas, retaining original minimum dimensions.
    If that causes overlaps, try the original layout fitted to the canvas. If
    even that is unsafe, retain the entire original page. Fixed visuals always
    participate in overlap checks. No rejected model geometry reaches the writer.
    """
    check_plan_identity(plan, pages)
    proposed = {(v["page"], v["visual"]): v for v in plan["placements"]}
    placements, adjustments = [], []
    for page in pages:
        movable = [v for v in page["visuals"] if v["movable"]]
        original = [{"page": page["page"], "visual": v["visual"], **{k: v[k] for k in BOUNDS}} for v in movable]
        raw = [proposed[(page["page"], v["visual"])] for v in movable]
        candidate = [fit_bounds(p, v, page) for p, v in zip(raw, movable)]
        action = "fitted_to_canvas"
        reason = "Önerilen konum ve boyutlar sayfa sınırlarına uyarlandı; mevcut görseller küçültülmedi."
        try:
            check_plan({"placements": candidate}, [page])
        except ValueError as exc:
            reason = str(exc)
            candidate = [fit_bounds(p, v, page) for p, v in zip(original, movable)]
            action = "original_layout_fitted"
            try:
                check_plan({"placements": candidate}, [page])
            except ValueError:
                candidate = original
                action = "original_layout_preserved"
                check_plan({"placements": candidate}, [page])
        if candidate != raw:
            adjustments.append({"page": page["page"], "action": action, "reason": reason,
                                "proposed": raw, "applied": candidate})
        placements.extend(candidate)
    result = {"placements": placements}
    check_plan(result, pages)
    return result, adjustments


def plain_expression(value):
    if isinstance(value, list):
        return all(plain_expression(v) for v in value)
    if not isinstance(value, dict):
        return True
    if "expr" in value:
        return set(value) == {"expr"} and isinstance(value["expr"], dict) and set(value["expr"]) <= {"Literal", "ThemeDataColor"}
    return all(plain_expression(v) for v in value.values())


def set_property(container, group, prop, value, changes, prefix):
    """Only default, unconditional formatting; preserve selector/conditional rules."""
    existing = container.get(group)
    if existing is not None and (not isinstance(existing, list) or len(existing) != 1 or not isinstance(existing[0], dict)
                                 or existing[0].get("selector") is not None):
        return
    if existing is not None:
        props = existing[0].get("properties", {})
        if not isinstance(props, dict):
            return
        if prop in props and not plain_expression(props[prop]):
            return
    else:
        container[group] = [{"properties": {}}]
    props = container[group][0].setdefault("properties", {})
    if props.get(prop) != value:
        props[prop] = deepcopy(value)
        changes.append(prefix + (group, 0, "properties", prop))


def apply_design(layout, inventory, style, plan):
    edited = deepcopy(layout)
    changes = []
    placements = {(p["page"], p["visual"]): p for p in plan["placements"]}
    for page in inventory:
        si = page["page"]
        section = edited["sections"][si]
        sc = parsed_config(section)
        # Preserve unsupported page composition (groups/bookmarks/custom visuals).
        if page["visuals"] and all(v["editable"] for v in page["visuals"]):
            objects = sc.setdefault("objects", {})
            background = objects.get("background", [])
            has_image = any("image" in x.get("properties", {}) for x in background)
            if not has_image:
                prefix = ("sections", si, "config", "objects")
                set_property(objects, "background", "color", color(style["background"]), changes, prefix)
                set_property(objects, "background", "transparency", literal(0), changes, prefix)
                section["config"] = json_text(sc)
        for item in page["visuals"]:
            if not item["editable"]:
                continue
            vi = item["visual"]
            visual = section["visualContainers"][vi]
            config = parsed_config(visual)
            base = ("sections", si, "visualContainers", vi)
            placement = placements.get((si, vi))
            if placement:
                desktop_index = next(i for i, x in enumerate(config["layouts"]) if x.get("id") == 0)
                position = config["layouts"][desktop_index]["position"]
                for key in ("x", "y", "width", "height"):
                    value = placement[key]
                    if visual[key] != value:
                        visual[key] = value
                        changes.append(base + (key,))
                    if position.get(key) != value:
                        position[key] = value
                        changes.append(base + ("config", "layouts", desktop_index, "position", key))
            sv = config["singleVisual"]
            objects = sv.setdefault("vcObjects", {})
            prefix = base + ("config", "singleVisual", "vcObjects")
            for group, prop, value in [
                ("background", "color", color(style["surface"])),
                ("background", "transparency", literal(0)),
                ("border", "show", literal(True)),
                ("border", "color", color(style["border"])),
                ("border", "radius", literal(style["radius"])),
                ("title", "fontColor", color(style["text"])),
                ("title", "fontFamily", literal(style["font"])),
                ("title", "fontSize", literal(style["title_size"])),
            ]:
                set_property(objects, group, prop, value, changes, prefix)
            chart = sv.get("objects", {})
            prefix = base + ("config", "singleVisual", "objects")
            kind = item["type"]
            if kind in {"tableEx", "pivotTable"}:
                sv["objects"] = chart
                table_styles = [("grid", "textSize", literal(style["body_size"])),
                                ("columnHeaders", "fontColor", color(style["text"])),
                                ("columnHeaders", "backColor", color(style["header"])),
                                ("columnHeaders", "fontFamily", literal(style["font"])),
                                ("values", "fontColorPrimary", color(style["text"])),
                                ("values", "backColorPrimary", color(style["surface"]))]
                for group, prop, value in table_styles:
                    set_property(chart, group, prop, value, changes, prefix)
            elif kind in CHARTS:
                # Preserve series colors, scales, labels/legend visibility, data
                # precision, sorting, conditional formatting and all data bindings.
                for group in ("categoryAxis", "valueAxis", "legend"):
                    if group in chart:
                        set_property(chart, group, "fontSize", literal(style["body_size"]), changes, prefix)
                        set_property(chart, group, "labelColor", color(style["muted"]), changes, prefix)
                # Data label colors remain untouched (inside/outside positioning
                # requires rendered data and cannot be inferred reliably here).
            visual["config"] = json_text(config)
    return edited, changes


VC_ALLOWED = {("background", "color"), ("background", "transparency"), ("border", "show"),
              ("border", "color"), ("border", "radius"), ("title", "fontColor"),
              ("title", "fontFamily"), ("title", "fontSize")}
OBJECT_ALLOWED = {("grid", "textSize"), ("columnHeaders", "fontColor"), ("columnHeaders", "backColor"),
                  ("columnHeaders", "fontFamily"), ("values", "fontColorPrimary"), ("values", "backColorPrimary")}
OBJECT_ALLOWED |= {(group, prop) for group in ("categoryAxis", "valueAxis", "legend") for prop in ("fontSize", "labelColor")}


def expanded(layout):
    result = deepcopy(layout)
    for section in result["sections"]:
        section["config"] = parsed_config(section)
        for visual in section["visualContainers"]:
            visual["config"] = parsed_config(visual)
    return result


def allowed_path(path):
    if len(path) < 4 or path[0] != "sections" or type(path[1]) is not int:
        return False
    if path[2:4] == ("config", "objects"):
        return len(path) == 8 and path[4] == "background" and path[5:7] == (0, "properties") and path[7] in {"color", "transparency"}
    if path[2] != "visualContainers" or type(path[3]) is not int:
        return False
    rest = path[4:]
    if len(rest) == 1:
        return rest[0] in {"x", "y", "width", "height"}
    if len(rest) == 5 and rest[:2] == ("config", "layouts") and type(rest[2]) is int and rest[3] == "position":
        return rest[4] in {"x", "y", "width", "height"}
    if len(rest) == 7 and rest[:2] == ("config", "singleVisual") and rest[4:6] == (0, "properties"):
        choices = VC_ALLOWED if rest[2] == "vcObjects" else OBJECT_ALLOWED if rest[2] == "objects" else set()
        return (rest[3], rest[6]) in choices
    return False


def verify_layout(before, after, changes):
    if not all(allowed_path(path) for path in changes):
        raise ValueError("Görsel izin listesinin dışında değişiklik engellendi.")
    a, b = expanded(before), expanded(after)
    allowed = set(changes)
    missing = object()

    def compare(left, right, path=()):
        if path in allowed:
            return
        if left == right:
            return
        if isinstance(left, dict) or isinstance(right, dict):
            if left is missing:
                left = {}
            if right is missing:
                right = {}
            if isinstance(left, dict) and isinstance(right, dict) and (left or right):
                for key in set(left) | set(right):
                    compare(left.get(key, missing), right.get(key, missing), path + (key,))
                return
        if isinstance(left, list) or isinstance(right, list):
            if left is missing:
                left = []
            if right is missing:
                right = []
            if isinstance(left, list) and isinstance(right, list) and (left or right):
                for index in range(max(len(left), len(right))):
                    compare(left[index] if index < len(left) else missing,
                            right[index] if index < len(right) else missing, path + (index,))
                return
        raise ValueError("Analitik koruma kontrolü başarısız. Çıktı oluşturulmadı: " + str(path))

    compare(a, b)


def remove_integrity_reference(raw):
    text = raw.decode("utf-8-sig")
    if "<!DOCTYPE" in text or "<!ENTITY" in text:
        raise ValueError("Desteklenmeyen paket tanımı.")
    root = ET.fromstring(text)
    original = deepcopy(root)
    namespace = "{http://schemas.openxmlformats.org/package/2006/content-types}"
    targets = [node for node in root if node.tag == namespace + "Override" and node.get("PartName") == "/SecurityBindings"]
    for node in targets:
        root.remove(node)
    if not targets:
        return raw
    ET.register_namespace("", namespace[1:-1])
    encoded = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    # Verify the manifest modification is limited to the stale integrity entry.
    for node in list(original):
        if node.tag == namespace + "Override" and node.get("PartName") == "/SecurityBindings":
            original.remove(node)
    if ET.tostring(original) != ET.tostring(ET.fromstring(encoded)):
        raise ValueError("Paket tanımı doğrulanamadı.")
    return encoded


def write_package(destination, entries, parts, comment, layout_bytes):
    replacement = {"Report/Layout": layout_bytes}
    if "SecurityBindings" in parts:
        # This package-integrity record becomes stale on external edits. It is
        # distinct from model roles/RLS, which stay in the unchanged model part.
        # Power BI Desktop re-export is required for native validation/re-signing.
        if "[Content_Types].xml" not in parts:
            raise ValueError("Paket tanımı bulunamadı.")
        replacement["[Content_Types].xml"] = remove_integrity_reference(parts["[Content_Types].xml"])
    temporary = destination.with_suffix(".pending")
    if destination.exists():
        raise ValueError("Çıktı dosyası zaten var; üzerine yazılmadı.")
    try:
        with zipfile.ZipFile(temporary, "w") as archive:
            archive.comment = comment
            for entry in entries:
                if entry.filename != "SecurityBindings":
                    archive.writestr(deepcopy(entry), replacement.get(entry.filename, parts[entry.filename]))
        with zipfile.ZipFile(temporary) as archive:
            if archive.testzip() is not None:
                raise ValueError("Çıktı paket bütünlüğü doğrulanamadı.")
            if set(archive.namelist()) != set(parts) - {"SecurityBindings"}:
                raise ValueError("Beklenmeyen paket parçası değişikliği.")
            for name, data in parts.items():
                if name not in replacement and name != "SecurityBindings" and archive.read(name) != data:
                    raise ValueError("Korunan paket parçası değişti: " + name)
            if archive.read("Report/Layout") != layout_bytes:
                raise ValueError("Rapor düzeni doğrulanamadı.")
        temporary.replace(destination)
    finally:
        temporary.unlink(missing_ok=True)
