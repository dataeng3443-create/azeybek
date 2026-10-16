"""Read a dashboard screenshot (PNG) and extract its colours and composition.

Everything happens locally with Pillow: the local text model never sees pixels.
Output (all coordinates normalised to 0..1):
    colors   background / surface / text / muted / accent / secondary / banner …
    banner   title band rectangle or None
    small    KPI-sized card rectangles
    large    chart-sized card rectangles
    sidebar  tall left/right filter panel or None
"""
from __future__ import annotations

from collections import Counter, deque
import colorsys
import warnings

from PIL import Image, UnidentifiedImageError

import styles

WORK_WIDTH = 360


def load(path):
    """Decode safely (bomb limits, odd PNG modes) into an RGB image on white."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as source:
                if source.format != "PNG":
                    raise ValueError("Referans görsel geçerli bir PNG değil.")
                width, height = source.size
                if max(width, height) > 12000 or width * height > 40_000_000:
                    raise ValueError("Referans PNG en fazla 12000 piksel kenar ve 40 milyon piksel içerebilir.")
                source.verify()
            with Image.open(path) as source:
                source.load()
                if source.mode.startswith("I;16") or source.mode == "I":
                    source = source.point(lambda value: value / 257).convert("L")
                try:
                    sample = source.convert("RGBA")
                except (OSError, ValueError):
                    sample = source.convert("RGB").convert("RGBA")
                background = Image.new("RGBA", sample.size, "white")
                image = Image.alpha_composite(background, sample).convert("RGB")
    except (Image.DecompressionBombWarning, Image.DecompressionBombError) as exc:
        raise ValueError("Referans PNG işlenebilecek piksel sınırını aşıyor.") from exc
    except (UnidentifiedImageError, OSError, SyntaxError) as exc:
        raise ValueError("Referans PNG dosyası bozuk veya eksik. Yeniden dışa aktarıp deneyin.") from exc
    return image, width, height


def _q(p, step=8):
    return (p[0] // step, p[1] // step, p[2] // step)


def _mode(pixels, step=8):
    """Average colour of the most common quantised bucket."""
    if not pixels:
        return None
    counts = Counter(_q(p, step) for p in pixels)
    bucket = counts.most_common(1)[0][0]
    members = [p for p in pixels if _q(p, step) == bucket]
    return tuple(sum(p[i] for p in members) / len(members) for i in range(3))


def _dist(a, b):
    return ((a[0] - b[0]) ** 2 + (a[1] - b[1]) ** 2 + (a[2] - b[2]) ** 2) ** .5


def _hex(p):
    return styles.hex_color(p)


def _components(mask, width, x0, y0, x1, y1):
    """4-connected components of True cells inside a window; returns bboxes."""
    seen = set()
    result = []
    for y in range(y0, y1):
        row = y * width
        for x in range(x0, x1):
            index = row + x
            if not mask[index] or index in seen:
                continue
            queue = deque([index])
            seen.add(index)
            minx = maxx = x
            miny = maxy = y
            count = 0
            members = []
            while queue:
                current = queue.popleft()
                count += 1
                members.append(current)
                cy, cx = divmod(current, width)
                minx, maxx, miny, maxy = min(minx, cx), max(maxx, cx), min(miny, cy), max(maxy, cy)
                for nx, ny in ((cx + 1, cy), (cx - 1, cy), (cx, cy + 1), (cx, cy - 1)):
                    if x0 <= nx < x1 and y0 <= ny < y1:
                        n = ny * width + nx
                        if mask[n] and n not in seen:
                            seen.add(n)
                            queue.append(n)
            result.append({"x0": minx, "y0": miny, "x1": maxx + 1, "y1": maxy + 1, "count": count, "members": members})
    return result


def _cards(pixels, width, height):
    frame = [pixels[i] for i in range(width * 2)] + [pixels[i] for i in range(width * (height - 2), width * height)]
    frame += [pixels[y * width + x] for y in range(height) for x in (0, 1, width - 2, width - 1)]
    background = _mode(frame)
    mask = [_dist(p, background) > 12 for p in pixels]
    comps = _components(mask, width, 0, 0, width, height)
    area = width * height
    cards = []
    for comp in comps:
        w, h = comp["x1"] - comp["x0"], comp["y1"] - comp["y0"]
        if w < width * .06 or h < height * .06 or w * h < area * .008:
            continue
        # Fill ratio: real panels are solid; scattered glyph clusters are not.
        if comp["count"] < w * h * .35:
            continue
        comp["fill"] = _mode([pixels[i] for i in comp["members"]], 6)
        cards.append(comp)
    # A large panel that holds several cards (e.g. a white sheet with grey tiles).
    expanded = []
    for card in cards:
        w, h = card["x1"] - card["x0"], card["y1"] - card["y0"]
        children, covered = [], 0
        if w * h > area * .2:
            local = card["fill"]
            inner = list(mask)
            member_set = set(card["members"])
            for y in range(card["y0"], card["y1"]):
                for x in range(card["x0"], card["x1"]):
                    i = y * width + x
                    inner[i] = i in member_set and _dist(pixels[i], local) > 5
            for comp in _components(inner, width, card["x0"], card["y0"], card["x1"], card["y1"]):
                cw, ch = comp["x1"] - comp["x0"], comp["y1"] - comp["y0"]
                if cw * ch >= area * .02 and comp["count"] >= cw * ch * .35 and cw >= width * .08 and ch >= height * .08:
                    comp["fill"] = _mode([pixels[i] for i in comp["members"]], 6)
                    children.append(comp)
            covered = sum((c["x1"] - c["x0"]) * (c["y1"] - c["y0"]) for c in children)
        if len(children) >= 2 and covered >= w * h * .35:
            expanded.extend(children)
        else:
            expanded.append(card)
    return background, expanded


def _palette(pixels, width, height, background, cards, banner):
    inside = []
    for card in cards:
        inside.extend(card["members"][::3])
    surface = _mode([pixels[i] for i in inside], 6) if inside else background
    dark = sum(background) / 3 < 90
    saturated = Counter()
    sums = {}
    for index in range(0, len(pixels), 2):
        if banner and banner["x0"] <= index % width < banner["x1"] and banner["y0"] <= index // width < banner["y1"]:
            continue
        r, g, b = pixels[index]
        h, s, v = colorsys.rgb_to_hsv(r / 255, g / 255, b / 255)
        if s > .3 and .25 < v < .97:
            key = int(h * 24) % 24
            saturated[key] += 1
            total = sums.setdefault(key, [0, 0, 0])
            total[0] += r; total[1] += g; total[2] += b
    def mean(key):
        n = saturated[key]
        return tuple(c / n for c in sums[key])
    accent = secondary = None
    ranked = saturated.most_common()
    if ranked and ranked[0][1] > len(pixels) * .002:
        accent = mean(ranked[0][0])
        for key, count in ranked[1:]:
            distance = min(abs(key - ranked[0][0]), 24 - abs(key - ranked[0][0]))
            if distance >= 3 and count >= ranked[0][1] * .08:
                secondary = mean(key)
                break
    # Text: the darkest (or lightest on dark themes) frequent colour on cards.
    tones = [p for p in (pixels[i] for i in inside) if max(p) - min(p) < 28]
    if dark:
        candidates = [p for p in tones if sum(p) / 3 > 190]
    else:
        candidates = [p for p in tones if sum(p) / 3 < 80]
    text = _mode(candidates, 16) if len(candidates) > 20 else ((240, 244, 250) if dark else (28, 32, 46))
    colors = {"background": _hex(background), "surface": _hex(surface), "text": _hex(text)}
    colors["muted"] = styles.mix(colors["text"], colors["surface"], .35)
    if accent:
        colors["accent"] = _hex(accent)
        colors["secondary"] = _hex(secondary) if secondary else styles.mix(colors["accent"], "#000000" if not dark else "#FFFFFF", .35)
    if banner:
        region = [pixels[y * width + x] for y in range(banner["y0"], banner["y1"]) for x in range(banner["x0"], banner["x1"], 2)]
        body = [p for p in region if _dist(p, banner["fill"]) < 90] or region
        colors["banner"] = _hex(tuple(sum(p[i] for p in body) / len(body) for i in range(3)))
    else:
        colors["banner"] = colors.get("accent", colors["text"]) if not dark else colors["surface"]
    return colors, dark


def reference_profile(path):
    image, width, height = load(path)
    work_w = min(WORK_WIDTH, width)
    work_h = max(1, min(900, round(height * work_w / width)))
    small = image.resize((work_w, work_h), Image.BILINEAR) if (work_w, work_h) != image.size else image
    pixels = list(small.getdata())
    background, cards = _cards(pixels, work_w, work_h)

    def norm(c):
        return {"x": c["x0"] / work_w, "y": c["y0"] / work_h, "w": (c["x1"] - c["x0"]) / work_w, "h": (c["y1"] - c["y0"]) / work_h}

    banner = None
    small_slots, large_slots, sidebar = [], [], None
    for card in sorted(cards, key=lambda c: (c["y0"], c["x0"])):
        n = norm(card)
        if banner is None and n["y"] < .12 and n["w"] > .6 and n["h"] < .2:
            banner = card
            continue
        if n["h"] > .55 and n["w"] < .24 and (n["x"] < .05 or n["x"] + n["w"] > .95) and sidebar is None:
            sidebar = card
            continue
        if n["h"] < .24 and n["w"] * n["h"] < .07:
            small_slots.append(n)
        else:
            large_slots.append(n)
    colors, dark = _palette(pixels, work_w, work_h, background, cards, banner)
    style = styles.build_style(colors)
    areas = sorted(s["w"] * s["h"] for s in large_slots)
    composition = "spotlight" if len(areas) > 1 and areas[-1] >= 1.4 * areas[len(areas) // 2] else \
        ("spotlight" if width / height >= 1.35 and not large_slots else "balanced")
    return {"width": width, "height": height, "aspect": width / height,
            "palette": styles.nearest_palette(style["accent"]), "dark": dark,
            "colors": {k: style[k] for k in ("background", "surface", "text", "muted", "border", "header",
                                             "accent", "secondary", "banner", "banner_text")},
            "banner": norm(banner) if banner else None, "sidebar": norm(sidebar) if sidebar else None,
            "small": small_slots, "large": large_slots, "composition": composition}
