"""Deterministic page layout engines.

The language model only decides hierarchy (priority) and chart semantics; these
functions turn that into collision-free rectangles that stay inside the canvas.

Items are dicts: {"key", "group", "order", "priority", "w", "h", "text_len"} where
group is one of header / decor / kpi / filter / chart.
"""
from __future__ import annotations

import math

MARGIN, GAP = 24, 16
KPI_H, MIN_CHART_H = 104, 210


def _rect(x, y, w, h):
    return {"x": round(x), "y": round(y), "width": max(1, round(w)), "height": max(1, round(h))}


def _overlap(a, b):
    return max(0, min(a["x"] + a["width"], b["x"] + b["width"]) - max(a["x"], b["x"])) * \
        max(0, min(a["y"] + a["height"], b["y"] + b["height"]) - max(a["y"], b["y"]))


def valid(rects, width, height):
    values = list(rects.values())
    for r in values:
        if r["x"] < 0 or r["y"] < 0 or r["width"] <= 0 or r["height"] <= 0 \
                or r["x"] + r["width"] > width or r["y"] + r["height"] > height:
            return False
    return all(_overlap(a, b) == 0 for i, a in enumerate(values) for b in values[i + 1:])


def _split(items):
    groups = {g: [] for g in ("header", "decor", "kpi", "filter", "chart")}
    for item in items:
        groups[item["group"]].append(item)
    for g in ("header", "decor", "kpi", "filter"):
        groups[g].sort(key=lambda v: v["order"])
    groups["chart"].sort(key=lambda v: (v["priority"], v["order"]))
    return groups


def _header_band(groups, x0, y, usable, rects):
    """Title band (first textbox + logos/buttons), then any extra text rows."""
    headers, decor = groups["header"], groups["decor"]
    if not headers and not decor:
        return y
    first = headers[0] if headers else None
    if first:
        lines = max(1, math.ceil(first["text_len"] * 11 / max(200, usable * .7)))
        band = max(56, min(140, max(min(first["h"], 96), 24 + lines * 32)))
    else:
        band = max(48, min(96, max(d["h"] for d in decor)))
    right = x0 + usable
    for item in reversed(decor):
        scale = min(1, band / max(1, item["h"]))
        w = min(item["w"] * scale, usable * .25)
        h = min(item["h"] * scale, band)
        right -= w
        rects[item["key"]] = _rect(right, y + (band - h) / 2, w, h)
        right -= GAP
    if first:
        rects[first["key"]] = _rect(x0, y, max(80, right - x0), band)
    y += band + GAP
    for item in headers[1:]:
        h = max(40, min(item["h"], 120))
        rects[item["key"]] = _rect(x0, y, usable, h)
        y += h + GAP
    return y


def _row(items, x0, y, usable, h, rects, weights=None):
    weights = weights or [1] * len(items)
    total = sum(weights)
    free = usable - GAP * (len(items) - 1)
    x = x0
    for item, weight in zip(items, weights):
        w = free * weight / total
        rects[item["key"]] = _rect(x, y, w, h)
        x += w + GAP


def _chart_rows(n, composition, usable):
    spotlight = composition == "spotlight"
    if n <= 0:
        return []
    if n == 1:
        return [1]
    if n == 2:
        return [2]
    if n == 3:
        return [3] if not spotlight and usable >= 900 else ([2, 1] if not spotlight else "L")
    if n == 4:
        return [2, 2]
    if n == 5:
        return [2, 3] if spotlight else [3, 2]
    per = 3 if usable >= 900 else 2
    rows = [per] * (n // per)
    if n % per:
        rows.append(n % per)
    return rows


def arrange(width, height, items, composition="spotlight"):
    """Grid layout: title band → KPI/filter row → charts with a spotlight."""
    groups = _split(items)
    rects = {}
    usable = width - 2 * MARGIN
    y = _header_band(groups, MARGIN, MARGIN, usable, rects)
    kpis, filters = groups["kpi"], groups["filter"]
    filter_h = max(56, min(140, max((f["h"] for f in filters), default=56)))
    if kpis and filters and len(kpis) + len(filters) <= 6:
        h = max(KPI_H, filter_h)
        _row(kpis + filters, MARGIN, y, usable, h, rects)
        y += h + GAP
    else:
        for row_items, h in ((kpis, KPI_H), (filters, filter_h)):
            for start in range(0, len(row_items), 6):
                _row(row_items[start:start + 6], MARGIN, y, usable, h, rects)
                y += h + GAP
    charts = groups["chart"]
    pattern = _chart_rows(len(charts), composition, usable)
    if pattern == "L":
        rows_needed = 2
    else:
        rows_needed = len(pattern)
    if rows_needed:
        available = height - MARGIN - y
        row_h = (available - GAP * (rows_needed - 1)) / rows_needed
        if row_h < MIN_CHART_H:
            row_h = MIN_CHART_H
        if pattern == "L":
            big_w = (usable - GAP) * .6
            total_h = row_h * 2 + GAP
            rects[charts[0]["key"]] = _rect(MARGIN, y, big_w, total_h)
            small_w = usable - GAP - big_w
            rects[charts[1]["key"]] = _rect(MARGIN + big_w + GAP, y, small_w, row_h)
            rects[charts[2]["key"]] = _rect(MARGIN + big_w + GAP, y + row_h + GAP, small_w, row_h)
            y += total_h + GAP
        else:
            index = 0
            weights_first = 1.25 if composition == "spotlight" and len(pattern) > 1 else 1
            total_weight = weights_first + (len(pattern) - 1)
            free_h = row_h * len(pattern)
            for r, count in enumerate(pattern):
                h = free_h * (weights_first if r == 0 else 1) / total_weight
                h = max(MIN_CHART_H * (.9 if r else 1), h)
                row = charts[index:index + count]
                weights = None
                if composition == "spotlight" and r == 0 and count == 2:
                    weights = [.6, .4]
                elif composition == "spotlight" and r == 0 and count == 3:
                    weights = [.4, .3, .3]
                _row(row, MARGIN, y, usable, h, rects, weights)
                index += count
                y += h + GAP
    page_height = max(height, math.ceil(y - GAP + MARGIN))
    if page_height > 20000:
        raise ValueError("Yeniden tasarlanan sayfa desteklenen tuval yüksekliğini aşıyor.")
    return page_height, rects


# ------------------------------------------------------------ reference slots
def _bands(slots):
    """Group normalized rectangles into horizontal bands (rows)."""
    bands = []
    for slot in sorted(slots, key=lambda s: (s["y"], s["x"])):
        centre = slot["y"] + slot["h"] / 2
        for band in bands:
            if band["y0"] - .01 <= centre <= band["y1"] + .01:
                band["slots"].append(slot)
                band["y0"] = min(band["y0"], slot["y"])
                band["y1"] = max(band["y1"], slot["y"] + slot["h"])
                break
        else:
            bands.append({"y0": slot["y"], "y1": slot["y"] + slot["h"], "slots": [slot]})
    for band in bands:
        band["slots"].sort(key=lambda s: s["x"])
    return sorted(bands, key=lambda b: b["y0"])


def fit_to_slots(width, height, items, profile, composition="spotlight"):
    """Re-create the reference image's composition (banner, KPI row, chart grid).

    Returns (page_height, rects) or None when the reference has no usable
    structure or the result would not be collision free (caller then uses arrange).
    """
    if not profile or not profile.get("large") and not profile.get("small"):
        return None
    groups = _split(items)
    aspect = profile.get("aspect") or width / height
    page_h = height if abs(width / height - aspect) / aspect < .15 else max(360, min(4000, round(width / aspect)))
    content = profile.get("small", []) + profile.get("large", [])
    sidebar = profile.get("sidebar") if groups["filter"] else None
    if sidebar:
        content = content + [sidebar]
    min_x = min(s["x"] for s in content)
    max_x = max(s["x"] + s["w"] for s in content)
    left = max(MARGIN / 2, min_x * width)
    right = min(width - MARGIN / 2, max_x * width)
    span = right - left
    rects = {}
    banner = profile.get("banner")
    # Banner / title band.
    if banner and (groups["header"] or groups["decor"]):
        band_h = max(48, min(140, banner["h"] * page_h))
        top = max(0, banner["y"] * page_h)
        bx = max(0, banner["x"] * width)
        bw = min(width - bx, banner["w"] * width)
        _header_band({"header": groups["header"][:1], "decor": groups["decor"]}, bx, top, bw, rects)
        # Keep exact banner height from the reference for the title textbox.
        if groups["header"]:
            key = groups["header"][0]["key"]
            rects[key]["height"] = round(band_h)
        y = top + band_h + GAP
    else:
        y = _header_band({"header": groups["header"][:1], "decor": groups["decor"]}, left, MARGIN, span, rects)
    for item in groups["header"][1:]:
        h = max(40, min(item["h"], 100))
        rects[item["key"]] = _rect(left, y, span, h)
        y += h + GAP

    def sx(slot):
        x0 = left if sidebar is None and not groups["filter"] and profile.get("sidebar") else None
        if x0 is None:
            return slot["x"] * width, slot["w"] * width
        # An unused reference sidebar: stretch the content to the full width.
        cx = [s for s in content if s is not profile.get("sidebar")]
        lo = min(s["x"] for s in cx)
        hi = max(s["x"] + s["w"] for s in cx)
        scale = (width - 2 * MARGIN) / max(1e-6, (hi - lo) * width)
        return MARGIN + (slot["x"] - lo) * width * scale, slot["w"] * width * scale

    # Build used bands, top to bottom.
    small_items = groups["kpi"] + ([] if sidebar else groups["filter"])
    plan = []  # (kind, band, items)
    small_bands = _bands(profile.get("small", []))
    for band in small_bands:
        if not small_items:
            break
        take = small_items[:len(band["slots"])]
        small_items = small_items[len(take):]
        plan.append(("small", band, take))
    while small_items:   # more KPIs/filters than the reference shows
        take, small_items = small_items[:6], small_items[6:]
        plan.append(("small_extra", None, take))
    charts = list(groups["chart"])
    large_bands = _bands(profile.get("large", []))
    # Use as few reference rows as needed and spread the charts evenly over them
    # (4 charts on a 3+3 reference become 2+2 rather than 3+1).
    needed, capacity = 0, 0
    while needed < len(large_bands) and capacity < len(charts):
        capacity += len(large_bands[needed]["slots"])
        needed += 1
    remaining = min(len(charts), capacity)
    for i, band in enumerate(large_bands[:needed]):
        bands_left = needed - i
        count = min(len(band["slots"]), -(-remaining // bands_left))
        take = charts[:count]
        charts = charts[count:]
        remaining -= count
        plan.append(("large", band, take))
    extra_rows = []
    per = 3 if width >= 1600 else 2
    while charts:
        take, charts = charts[:per], charts[per:]
        extra_rows.append(take)

    # Vertical budget: small bands keep their pixel height; large bands share the rest.
    bottom = page_h - max(MARGIN / 2, (1 - max((s["y"] + s["h"] for s in content), default=1)) * page_h)
    fixed = sum(max(72, min(150, (b["y1"] - b["y0"]) * page_h)) if k == "small" else 96
                for k, b, _ in plan if k != "large") + GAP * max(0, len(plan) - 1)
    large_norm = sum(b["y1"] - b["y0"] for k, b, _ in plan if k == "large")
    sidebar_x = None
    if sidebar:
        sidebar_x = (sidebar["x"] * width, sidebar["w"] * width)
    free = bottom - y - fixed
    if any(k == "large" for k, _, _ in plan) and free < MIN_CHART_H * .8:
        return None
    top_of_content = y
    for kind, band, chunk in plan:
        if kind == "large":
            h = free * (band["y1"] - band["y0"]) / large_norm
        elif kind == "small":
            h = max(72, min(150, (band["y1"] - band["y0"]) * page_h))
        else:
            h = 96
        if band is not None and len(chunk) == len(band["slots"]):
            ordered = chunk
            if kind == "large":
                # Highest priority visual takes the widest slot of the band.
                slots_by_width = sorted(range(len(band["slots"])), key=lambda i: (-round(band["slots"][i]["w"] * 25), band["slots"][i]["x"]))
                ordered = [None] * len(chunk)
                for item, slot_index in zip(sorted(chunk, key=lambda v: (v["priority"], v["order"])), slots_by_width):
                    ordered[slot_index] = item
            for item, slot in zip(ordered, band["slots"]):
                x, w = sx(slot)
                rects[item["key"]] = _rect(x, y, w, h)
        else:
            if band is not None:
                xs = [sx(s) for s in band["slots"]]
                x0, x1 = xs[0][0], xs[-1][0] + xs[-1][1]
            elif sidebar_x:
                x0, x1 = sidebar_x[0] + sidebar_x[1] + GAP, right
            else:
                x0, x1 = left, right
            _row(chunk, x0, y, x1 - x0, h, rects)
        y += h + GAP
    if sidebar:
        sy = top_of_content
        for item in groups["filter"]:
            h = max(56, min(item["h"], 120))
            rects[item["key"]] = _rect(sidebar_x[0], sy, sidebar_x[1], h)
            sy += h + GAP
        y = max(y, sy)
    for row in extra_rows:
        _row(row, left, y, span, 260, rects)
        y += 260 + GAP
    page_height = max(page_h, math.ceil(y - GAP + MARGIN / 2))
    if len(rects) != len(items) or not valid(rects, width, page_height):
        return None
    return page_height, rects
