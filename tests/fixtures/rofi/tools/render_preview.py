#!/usr/bin/env python3
"""
Draws one preview image per animation preset, and one per category variant.

Rofi cannot show an animated preview: its binary only links
gdk_pixbuf_new_from_file_at_scale, the single-frame loader, and has no
gdk_pixbuf_animation_new_from_file at all. A GIF handed to it renders as its
first frame — for a fade-out animation, usually an empty rectangle.

So the preview is a strobe instead: the same window drawn at several points
along the preset's own motion, earlier phases fainter. It is computed from the
preset's numbers — its bezier curve, its duration, its style — not recorded off
the screen, which keeps it deterministic and reproducible in a test.

Presets go to DIR/<id>.png, variants to DIR/<category>/<id>.png.

Run:  python3 tools/render_preview.py [--out DIR]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw

REPO = Path(__file__).resolve().parent.parent
PRESET_DIR = REPO / "data" / "presets"
VARIANT_DIR = REPO / "data" / "animations"
DEFAULT_OUT = Path.home() / ".cache" / "rofi-launcher" / "anim-previews"

WIDTH, HEIGHT = 320, 200
BG = (16, 16, 16, 255)
FG = (255, 255, 255)
FRAME = (48, 48, 48, 255)

# The window drawn inside the tile, as a fraction of the tile. Kept small enough
# that a ghost trail has somewhere to go, and chunky enough to survive being
# scaled down to an icon.
BOX = (0.46, 0.34, 0.80, 0.66)


def bezier_y(points, t):
    """A cubic bezier from (0,0) to (1,1) with two control points, evaluated
    the way Hyprland's own curves are: t is the parameter, not the x value.

    Close enough for a picture. Sampling by x would need a solve per point and
    would not change what the image communicates."""
    if len(points) < 4:
        return t
    _, y0, _, y1 = points[0], points[1], points[2], points[3]
    u = 1 - t
    return 3 * u * u * t * y0 + 3 * u * t * t * y1 + t ** 3


def _duration(preset):
    """How long the preset's window animation takes, in Hyprland's units.

    The tile has to separate a fast preset from a slow one: without this,
    "Slide" and "Cinematic" differ only in numbers nobody sees and render as
    the same picture, which makes the grid useless for choosing between them.
    """
    animations = preset.get("animations") or {}
    for leaf in ("windowsOut", "windowsIn", "fadeOut", "workspaces", "layersIn",
                 "layersOut", "global"):
        spec = animations.get(leaf)
        if not spec:
            continue
        parts = [x.strip() for x in str(spec).split(",")]
        if len(parts) > 1:
            try:
                return float(parts[1])
            except ValueError:
                pass
    return 6.0


def _trail_shape(preset, motion):
    """(ghost count, how far the trail reaches) from the preset's own timing.

    A slow animation leaves a long trail with many steps; a quick one leaves a
    short, tight one. Both are read off the same number Hyprland uses."""
    if motion == "none":
        return 1, 0.0
    speed = _duration(preset)
    # Durations in practice run from about 3 (snappy) to 34 (the fog fade-out).
    weight = min(1.0, max(0.0, (speed - 3.0) / 12.0))
    count = 3 + round(4 * weight)
    reach = 0.34 + 0.46 * weight
    return count, reach


def _first_curve(preset):
    beziers = preset.get("beziers") or {}
    for points in beziers.values():
        if len(points) >= 4:
            return list(points)
    return [0.0, 0.75, 0.15, 1.0]  # Hyprland's own "default"


def _rect(scale=1.0, dx=0.0, dy=0.0):
    x0, y0, x1, y1 = BOX
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    hw, hh = (x1 - x0) / 2 * scale, (y1 - y0) / 2 * scale
    return (
        (cx - hw + dx) * WIDTH, (cy - hh + dy) * HEIGHT,
        (cx + hw + dx) * WIDTH, (cy + hh + dy) * HEIGHT,
    )


def _ghosts(motion, count, curve, reach):
    """The trailing positions, faintest first. The final window is drawn
    separately — these are only where it has been."""
    out = []
    for i in range(count - 1):
        t = i / max(1, count - 1)
        eased = bezier_y(curve, t)
        alpha = int(45 + 90 * t)
        if motion in ("slide", "slidefade"):
            out.append((_rect(dx=-reach * (1 - eased)), alpha))
        elif motion == "snapslide":
            # A snap: two ghosts bunched right against the window, none far out.
            out.append((_rect(dx=-reach * 0.35 * (1 - eased) - 0.03), alpha))
        elif motion == "drop":
            # Anticipation then a fall: the faintest ghost sits a little above,
            # the rest fall away below.
            lift = 0.08 if i == 0 else -reach * 0.9 * t
            out.append((_rect(dy=-lift), alpha))
        elif motion in INNER_MOTIONS:
            pass  # drawn over the window instead, see _inner_ghosts
        elif motion == "slidevert":
            out.append((_rect(dy=-reach * 0.95 * (1 - eased)), alpha))
        elif motion == "scale":
            # `eased` is deliberately not clamped: a curve that overshoots (the
            # bounce preset's does, ending above 1) then draws a ring wider than
            # the window, which is exactly what overshoot looks like.
            out.append((_rect(scale=0.30 + 0.80 * eased), alpha))
        elif motion == "bounce":
            # A halo of rings well outside the window, widest first: the window
            # overshot its size and settled back.
            #
            # They all have to sit outside: `scale` already draws rings that
            # start small, and anything drawn inside the window is painted over
            # by it, so an inner ring would make the two tiles identical at icon
            # size — which is exactly what happened before.
            out.append((_rect(scale=1.0 + 0.62 * (1 - t)), alpha))
    return out


# Motions whose trail lies inside the window's final outline. Drawn as ghosts
# they would be painted over by the window and the tile would be a plain white
# box — indistinguishable from "none". So they are cut into the window as dark
# outlines instead.
INNER_MOTIONS = ("zoom", "unfold", "pop")


def _inner_ghosts(motion, count, curve):
    out = []
    for i in range(count - 1):
        t = i / max(1, count - 1)
        eased = bezier_y(curve, t)
        shade = int(40 + 110 * t)
        if motion == "zoom":
            out.append((_rect(scale=0.08 + 0.7 * eased), shade))
        elif motion == "unfold":
            out.append((_rect_unfold(0.06 + 0.8 * eased), shade))
        elif motion == "pop":
            out.append((_rect(scale=0.72 + 0.22 * t), shade))
    return out


def _rect_unfold(height_scale):
    """The window squashed to a strip around its horizontal centre line."""
    x0, y0, x1, y1 = _rect()
    cy = (y0 + y1) / 2
    half = (y1 - y0) / 2 * height_scale
    return (x0, cy - half, x1, cy + half)


def _draw_ghost(draw, rect, alpha):
    """An outline plus a barely-there fill. Drawn onto a transparent overlay:
    PIL's rectangle writes the colour it is given rather than blending it, so
    the alpha has to end up in the pixels and be composited afterwards."""
    draw.rectangle(rect, fill=FG + (max(8, alpha // 6),), outline=FG + (alpha,), width=3)


def _draw_materialise(draw, rect, count, top=230):
    """A fade, drawn as vertical bands going from barely there to solid.

    A fade has nowhere to travel, so ghosts at the same place would stack into
    one flat rectangle and say nothing. Bands keep the "it is arriving" reading
    without pretending the window moves."""
    x0, y0, x1, y1 = rect
    step = (x1 - x0) / count
    for i in range(count):
        alpha = int(30 + ((top - 30) * i) / max(1, count - 1))
        draw.rectangle(
            [x0 + i * step, y0, x0 + (i + 1) * step, y1],
            fill=FG + (alpha,),
        )


def _draw_dust(draw, rect, preset):
    """The pixel cloud, shaped by the dissolve plugin's own numbers.

    block_size sets how chunky the debris is, spread how far sideways it goes,
    rise how far up, and dust_life how many particles are still around — so two
    dissolve presets that differ only in those numbers get visibly different
    pictures, which is the entire point of showing a picture."""
    plugin = preset.get("dissolve") or {}
    block = max(2, int(plugin.get("block_size", 4)))
    spread = float(plugin.get("spread", 0.55))
    rise = float(plugin.get("rise", 200))
    life = float(plugin.get("dust_life", 0.35))

    x0, y0, x1, y1 = rect
    width, height = x1 - x0, y1 - y0
    reach_x = width * (0.35 + spread)
    reach_y = height * (rise / 200.0) * 0.9

    # dust_life is how long a particle survives, and that is what separates a
    # crisp scatter from a haze. Long-lived debris is drawn as many big, faint,
    # overlapping flecks that blur together; short-lived debris as fewer, small,
    # opaque ones. Without this, two presets that differ only in dust_life came
    # out as the same picture — the flecks were the same size either way and the
    # difference averaged out the moment the tile was scaled to an icon.
    haze = min(1.0, life / 1.6)
    count = int(70 + 420 * life)
    size = block * (1.0 + 2.2 * haze)
    opacity = 230 - int(150 * haze)

    rng = _Rng(seed=int(block * 131 + spread * 977 + rise + life * 61))
    for _ in range(count):
        # Particles leave from the right-hand side and travel up and out, so the
        # window still reads as a window rather than as noise.
        origin = rng.next_float() ** 0.6
        px = x0 + width * (0.45 + 0.55 * rng.next_float()) + origin * reach_x
        py = y0 + height * rng.next_float() - origin * reach_y
        fade = int(opacity * (1 - origin) ** 1.4)
        if fade < 8:
            continue
        jitter = size * (0.7 + 0.6 * rng.next_float())
        draw.rectangle([px, py, px + jitter, py + jitter], fill=FG + (fade,))


class _Rng:
    """A tiny deterministic generator.

    random.Random would also be reproducible, but only as long as CPython's
    implementation of it never changes; the image is compared byte for byte in a
    test, so the arithmetic is spelled out here instead."""

    def __init__(self, seed):
        self.state = (seed * 2654435761) & 0xFFFFFFFF or 1

    def next_float(self):
        self.state ^= (self.state << 13) & 0xFFFFFFFF
        self.state ^= self.state >> 17
        self.state ^= (self.state << 5) & 0xFFFFFFFF
        self.state &= 0xFFFFFFFF
        return self.state / 0xFFFFFFFF


def render(preset):
    spec = preset.get("preview") or {}
    motion = spec.get("motion", "scale")
    curve = _first_curve(preset)
    count, reach = preset.get("_trail") or _trail_shape(preset, motion)

    image = Image.new("RGBA", (WIDTH, HEIGHT), BG)
    ImageDraw.Draw(image).rectangle([0, 0, WIDTH - 1, HEIGHT - 1], outline=FRAME)
    window = _rect()

    # Translucent parts go onto their own layer and are composited in. Drawing
    # them straight onto the image would paint them opaque — PIL's rectangle
    # does not blend, whatever draw mode it is given.
    trail = Image.new("RGBA", (WIDTH, HEIGHT), (0, 0, 0, 0))
    trail_draw = ImageDraw.Draw(trail)
    for rect, alpha in _ghosts(motion, count, curve, reach):
        _draw_ghost(trail_draw, rect, alpha)
    if motion == "dissolve":
        _draw_dust(trail_draw, window, preset)
    elif motion == "fade":
        _draw_materialise(trail_draw, window, count + 2)
    elif motion == "slowfade":
        # A long fade: a wide, pale gradient that starts far to the left and
        # never gets bright. Drawn the same way as `fade` but at the window's
        # size it was indistinguishable from it at icon size.
        x0, y0, x1, y1 = window
        wide = (x0 - (x1 - x0) * 1.1, y0 + 6, x1, y1 - 6)
        _draw_materialise(trail_draw, wide, count + 10, top=215)
    elif motion == "slidefade":
        # The style really is slidefade: it travels and it fades. Showing only
        # the travel made this identical to plain `slide`.
        _draw_materialise(trail_draw, window, count + 3)
    image = Image.alpha_composite(image, trail)

    draw = ImageDraw.Draw(image)
    # A fade is entirely the bands above; painting the window solid over them
    # would erase the only thing the tile has to say.
    if motion not in ("fade", "slidefade", "slowfade"):
        draw.rectangle(window, fill=FG)
    if motion == "dissolve" and float((preset.get("dissolve") or {}).get("wave", 0)) >= 0.95:
        # A strict top-to-bottom front: the upper part of the window is already
        # gone. Only for a strict front, so the shipped presets keep their tiles.
        x0, y0, x1, y1 = window
        draw.rectangle([x0, y0, x1, y0 + (y1 - y0) * 0.45], fill=BG[:3])
    if motion in INNER_MOTIONS:
        for rect, shade in _inner_ghosts(motion, count + 1, curve):
            draw.rectangle(rect, outline=(shade, shade, shade), width=3)

    if motion == "none":
        # Nothing moves, so say so with a shape rather than leaving a tile
        # indistinguishable from "scale" with its trail cropped off.
        cx = (window[0] + window[2]) / 2
        cy = (window[1] + window[3]) / 2
        draw.line([cx - 30, cy, cx + 30, cy], fill=BG[:3], width=9)

    return image.convert("RGB")


def ui_tiles():
    """Pictures for the tiles that are not an animation: back and the speeds.

    In the grid every tile has room for a picture; a tile without one is a big
    empty box that reads as broken."""
    tiles = {}
    back = Image.new("RGBA", (WIDTH, HEIGHT), BG)
    draw = ImageDraw.Draw(back)
    draw.rectangle([0, 0, WIDTH - 1, HEIGHT - 1], outline=FRAME)
    cy = HEIGHT / 2
    draw.line([WIDTH * 0.32, cy, WIDTH * 0.68, cy], fill=FG, width=12)
    draw.polygon([(WIDTH * 0.24, cy), (WIDTH * 0.40, cy - 34), (WIDTH * 0.40, cy + 34)], fill=FG)
    tiles["back"] = back.convert("RGB")
    for name, reach, count in (("fast", 0.12, 2), ("normal", 0.32, 4), ("slow", 0.62, 7)):
        tiles[f"speed-{name}"] = render({
            "animations": {"windowsIn": "1, 5, x"},
            "beziers": {},
            "preview": {"motion": "slide"},
            "_trail": (count, reach),
        })
    return tiles


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    args.out.mkdir(parents=True, exist_ok=True)
    jobs = [(path, args.out) for path in sorted(PRESET_DIR.glob("*.json"))]
    for folder in sorted(p for p in VARIANT_DIR.glob("*") if p.is_dir()):
        jobs += [(path, args.out / folder.name) for path in sorted(folder.glob("*.json"))]

    count = 0
    for path, out_dir in jobs:
        try:
            item = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            print(f"пропущен {path.name}: {exc}", file=sys.stderr)
            continue
        out_dir.mkdir(parents=True, exist_ok=True)
        # optimize=False and no timestamp chunk: the same file must produce the
        # same bytes on every run, or the determinism test is meaningless.
        render(item).save(out_dir / f"{item['id']}.png", "PNG", optimize=False)
        count += 1
    ui = args.out / "_ui"
    ui.mkdir(parents=True, exist_ok=True)
    for name, image in ui_tiles().items():
        image.save(ui / f"{name}.png", "PNG", optimize=False)
        count += 1
    print(f"{count} превью → {args.out}")


if __name__ == "__main__":
    main()
