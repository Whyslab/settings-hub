"""
Animation presets.

A preset is one JSON file describing the whole feel of the desktop at once:
window open/close, workspace transitions, layer surfaces, its own bezier curves,
and the hypr-dissolve plugin's parameters. Half a preset is not a look.

Two ways to put one on, and the difference matters:

  live preview   hyprctl keyword …   nothing is written; `hyprctl reload` undoes
                                     it completely (verified: keyword sets
                                     overridden=1, reload puts it back to 0)
  apply          generated file      survives reload and reboot

So previewing cannot damage a configuration, by construction rather than by
being careful.

On top of a preset, each of four categories can be tuned on its own: window
open, window close, workspace switching, menus and notifications (layer
surfaces). A category is either left "as in the preset" or replaced by a variant
from data/animations/<category>/, and each has a speed: fast, normal or slow.
What gets written is compose(preset, tuning) — the preset with those parts
swapped out — so the preset files themselves never change.

One invariant is enforced here rather than left to whoever writes a preset: when
the dissolve plugin is on, fadeOut and windowsOut must have the same duration.
The plugin measures the dissolve's progress by the window's alpha, which fadeOut
drives, while windowsOut drives the geometry. Split them and the window freezes
in place while its pixels are still flying.
"""
from __future__ import annotations

import html
import json
import subprocess
from pathlib import Path

from .. import hyprconf
from ..rows import MARK_ACTIVE, back_row, dim, note_row
from ..strings import LANG, t

PRESET_DIR = Path(__file__).resolve().parent.parent.parent / "data" / "presets"
CFG_DIR = Path.home() / ".config" / "rofi-launcher"
ACTIVE_FILE = CFG_DIR / "animation-preset"
PREVIEW_DIR = Path.home() / ".cache" / "rofi-launcher" / "anim-previews"


class PresetError(ValueError):
    """A preset that would misbehave if applied."""


def _localized(value):
    """A preset's name/description is either a plain string or {lang: string}."""
    if isinstance(value, dict):
        return value.get(LANG) or value.get("en") or next(iter(value.values()), "")
    return str(value or "")


def _duration(spec):
    """The speed field of "1, 20, default, popin 100%"."""
    parts = [p.strip() for p in str(spec).split(",")]
    if len(parts) < 2:
        return None
    try:
        return float(parts[1])
    except ValueError:
        return None


def validate(preset):
    """Raise PresetError if the preset is internally inconsistent."""
    pid = preset.get("id")
    if not pid:
        raise PresetError("preset has no id")

    plugin = preset.get("dissolve") or {}
    if not plugin.get("enabled"):
        return preset

    animations = preset.get("animations") or {}
    fade, windows = _duration(animations.get("fadeOut")), _duration(animations.get("windowsOut"))
    if fade is None or windows is None:
        raise PresetError(
            f'{pid}: dissolve is enabled, so both fadeOut and windowsOut must be set'
        )
    if fade != windows:
        raise PresetError(
            f"{pid}: dissolve is enabled but fadeOut ({fade}) and "
            f"windowsOut ({windows}) differ — the window would freeze mid-flight"
        )

    forbidden = set(plugin) & hyprconf.PROTECTED_PLUGIN_KEYS
    if forbidden:
        raise PresetError(
            f"{pid}: presets must not touch {', '.join(sorted(forbidden))} — "
            "those are protection, not decoration"
        )
    return preset


def load_all():
    """Every valid preset, ordered by the `order` field then by id."""
    out = []
    if not PRESET_DIR.is_dir():
        return out
    for path in sorted(PRESET_DIR.glob("*.json")):
        try:
            preset = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        try:
            validate(preset)
        except PresetError:
            continue
        out.append(preset)
    out.sort(key=lambda p: (p.get("order", 999), p.get("id", "")))
    return out


def get(preset_id):
    for preset in load_all():
        if preset["id"] == preset_id:
            return preset
    return None


def active_id():
    try:
        return ACTIVE_FILE.read_text(encoding="utf-8").strip()
    except OSError:
        return ""


def _set_active(preset_id):
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = ACTIVE_FILE.with_suffix(".tmp")
    tmp.write_text(preset_id + "\n", encoding="utf-8")
    tmp.replace(ACTIVE_FILE)


# ─────────────────────────── applying ───────────────────────────

def _keyword(*args):
    subprocess.run(["hyprctl", "keyword", *args], capture_output=True, check=False)


def apply_live(preset):
    """Put the preset on without writing anything. `hyprctl reload` undoes it."""
    validate(preset)
    for name, points in (preset.get("beziers") or {}).items():
        _keyword("bezier", f"{name}," + ",".join(str(p) for p in points))
    for leaf, spec in (preset.get("animations") or {}).items():
        _keyword("animation", f"{leaf},{spec}")
    for key, value in (preset.get("dissolve") or {}).items():
        if key in hyprconf.PROTECTED_PLUGIN_KEYS:
            continue
        _keyword(f"plugin:dissolve:{key}", str(value))


def revert_live():
    """Throw away everything apply_live did, back to what the config says."""
    subprocess.run(["hyprctl", "reload"], capture_output=True, check=False)


def notify(text):
    """Say something happened.

    Applying a preset changes how windows move, which is invisible until the
    next time a window opens — and picking the preset that is already on
    changes nothing at all. Without a word from the machine both look exactly
    like a menu that did not work.
    """
    subprocess.run(
        ["notify-send", "-a", "rofi-hub", "-i", "preferences-desktop-effects",
         t("sec_animations"), text],
        capture_output=True, check=False,
    )


def apply_persistent(preset):
    """Write the preset out and reload. Survives a reboot.

    A preset is "everything at once", so putting one on also drops whatever the
    categories had been tuned to — otherwise picking "Slide" would silently keep
    a dissolve on close from before and not look like Slide at all."""
    validate(preset)
    was_active = active_id() == preset["id"] and not tuning_is_custom(load_tuning())
    save_tuning(empty_tuning())
    path = hyprconf.write(compose(preset, empty_tuning()))
    _set_active(preset["id"])
    subprocess.run(["hyprctl", "reload"], capture_output=True, check=False)
    name = _localized(preset.get("name"))
    notify(t("anim_already", name=name) if was_active else t("anim_applied", name=name))
    return path


# ─────────────────────────── categories ───────────────────────────

VARIANT_DIR = PRESET_DIR.parent / "animations"
TUNING_FILE = CFG_DIR / "animation-tuning.json"

# The leaves each category owns. Replacing a category removes all of these from
# the preset first, so a leftover leaf from the preset cannot leak into the
# variant (the preset's specialWorkspace next to a variant's workspaces, say).
CATEGORY_LEAVES = {
    "open": ("windowsIn", "fadeIn"),
    "close": ("windowsOut", "fadeOut"),
    "workspaces": (
        "workspaces", "workspacesIn", "workspacesOut",
        "specialWorkspace", "specialWorkspaceIn", "specialWorkspaceOut",
    ),
    "layers": ("layersIn", "layersOut", "fadeLayersIn", "fadeLayersOut"),
}
CATEGORIES = tuple(CATEGORY_LEAVES)
CATEGORY_TITLE = {
    "open": "anim_cat_open",
    "close": "anim_cat_close",
    "workspaces": "anim_cat_workspaces",
    "layers": "anim_cat_layers",
}
# Leaves materialised when a speed is set on a category the preset leaves to
# Hyprland's inheritance. Children (workspacesIn, specialWorkspace…) inherit
# from these, so scaling the parent is enough.
MATERIALISE = {
    "open": ("windowsIn", "fadeIn"),
    "close": ("windowsOut", "fadeOut"),
    "workspaces": ("workspaces",),
    "layers": ("layersIn", "layersOut", "fadeLayersIn", "fadeLayersOut"),
}
BEZIER_PREFIX = {"open": "o_", "close": "c_", "workspaces": "w_", "layers": "l_"}
# What Hyprland falls back to for a leaf nobody set: `global`, whose built-in
# value is this. Checked with `hyprctl animations -j` on 0.56.2.
HYPR_GLOBAL_DEFAULT = "1, 8, default"

SPEEDS = {"fast": 0.6, "normal": 1.0, "slow": 1.6}
SPEED_ORDER = ("fast", "normal", "slow")
MIN_SPEED = 0.5

# A variant can only dissolve menus while windows dissolve too: the plugin
# dissolves windows whenever it is on, and layers only as an addition to that.
# When that does not hold, menus fall back to this variant instead.
LAYERS_FALLBACK = "fade"


def load_variants(category):
    """Every valid variant of one category, ordered by `order` then id."""
    out = []
    folder = VARIANT_DIR / category
    if category not in CATEGORY_LEAVES or not folder.is_dir():
        return out
    for path in sorted(folder.glob("*.json")):
        try:
            variant = json.loads(path.read_text(encoding="utf-8"))
            validate_variant(variant)
        except (OSError, ValueError):
            continue
        out.append(variant)
    out.sort(key=lambda v: (v.get("order", 999), v.get("id", "")))
    return out


def get_variant(category, variant_id):
    for variant in load_variants(category):
        if variant["id"] == variant_id:
            return variant
    return None


def validate_variant(variant):
    """Raise PresetError if a variant would misbehave once composed in."""
    vid = variant.get("id")
    category = variant.get("category")
    if not vid:
        raise PresetError("variant has no id")
    if category not in CATEGORY_LEAVES:
        raise PresetError(f"{vid}: unknown category {category!r}")

    animations = variant.get("animations") or {}
    stray = set(animations) - set(CATEGORY_LEAVES[category])
    if stray:
        raise PresetError(f"{category}/{vid}: sets leaves it does not own: {sorted(stray)}")
    for name in variant.get("beziers") or {}:
        if not name.startswith(BEZIER_PREFIX[category]):
            raise PresetError(
                f"{category}/{vid}: curve {name!r} must start with "
                f"{BEZIER_PREFIX[category]!r}, or two categories could redefine each other's"
            )

    plugin = variant.get("dissolve")
    if plugin is not None and category != "close":
        raise PresetError(f"{category}/{vid}: only window close may set the dissolve plugin")
    if plugin:
        forbidden = set(plugin) & (hyprconf.PROTECTED_PLUGIN_KEYS | {"layers"})
        if forbidden:
            raise PresetError(f"{category}/{vid}: must not set {sorted(forbidden)}")
        if plugin.get("enabled"):
            _require_same_duration(vid, animations, "fadeOut", "windowsOut")

    if variant.get("layers_dissolve") and category != "layers":
        raise PresetError(f"{category}/{vid}: layers_dissolve belongs to the layers category")
    if variant.get("layers_dissolve"):
        _require_same_duration(vid, animations, "fadeLayersOut", "layersOut")
    return variant


def _require_same_duration(pid, animations, fade_leaf, geometry_leaf):
    fade, geometry = _duration(animations.get(fade_leaf)), _duration(animations.get(geometry_leaf))
    if fade is None or geometry is None or fade != geometry:
        raise PresetError(
            f"{pid}: {fade_leaf} ({fade}) and {geometry_leaf} ({geometry}) must both be "
            "set and equal while it dissolves — the surface would freeze mid-flight"
        )


# ── tuning: what the user changed on top of the preset ──

def empty_tuning():
    return {"overrides": {}, "speed": {}}


def load_tuning():
    """The saved tuning, with anything unknown or broken quietly dropped.

    This file is written by the menu, but a hand edit or a variant removed in an
    update must not take the whole animations section down with it."""
    try:
        raw = json.loads(TUNING_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return empty_tuning()
    if not isinstance(raw, dict):
        return empty_tuning()
    tuning = empty_tuning()
    overrides, speeds = raw.get("overrides"), raw.get("speed")
    overrides = overrides if isinstance(overrides, dict) else {}
    speeds = speeds if isinstance(speeds, dict) else {}
    for category, vid in overrides.items():
        if category in CATEGORY_LEAVES and isinstance(vid, str) and get_variant(category, vid):
            tuning["overrides"][category] = vid
    for category, speed in speeds.items():
        known = isinstance(speed, str) and speed in SPEEDS and speed != "normal"
        if category in CATEGORY_LEAVES and known:
            tuning["speed"][category] = speed
    return tuning


def save_tuning(tuning):
    CFG_DIR.mkdir(parents=True, exist_ok=True)
    tmp = TUNING_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(tuning, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    tmp.replace(TUNING_FILE)


def tuning_is_custom(tuning):
    return bool(tuning.get("overrides") or tuning.get("speed"))


def _format_speed(value):
    return str(int(value)) if float(value).is_integer() else f"{value:g}"


def scale_spec(spec, factor):
    """"1, 20, default, popin 100%" at 0.6 → "1, 12, default, popin 100%".

    Hyprland's speed is a duration (bigger is slower), so a factor below 1 is
    faster. A disabled animation stays disabled."""
    parts = [p.strip() for p in str(spec).split(",")]
    if factor == 1 or len(parts) < 2 or parts[0] in ("0", "false"):
        return spec
    try:
        speed = float(parts[1])
    except ValueError:
        return spec
    parts[1] = _format_speed(max(MIN_SPEED, round(speed * factor, 1)))
    return ", ".join(parts)


def compose(preset, tuning):
    """The preset with the tuned categories swapped in — what actually gets written.

    Pure: reads variant files, touches nothing else. The result is shaped like a
    preset, so validate(), hyprconf and apply_live take it unchanged."""
    overrides = tuning.get("overrides") or {}
    speeds = tuning.get("speed") or {}

    animations = dict(preset.get("animations") or {})
    beziers = dict(preset.get("beziers") or {})
    plugin = dict(preset.get("dissolve") or {})
    preset_dissolves_menus = bool(plugin.get("enabled")) and bool(plugin.get("layers", 1))

    def swap_in(category, variant):
        for leaf in CATEGORY_LEAVES[category]:
            animations.pop(leaf, None)
        animations.update(variant.get("animations") or {})
        beziers.update(variant.get("beziers") or {})

    for category in CATEGORIES:
        variant = get_variant(category, overrides.get(category, ""))
        if variant is None:
            continue
        swap_in(category, variant)
        if category == "close":
            plugin = dict(variant.get("dissolve") or {"enabled": 0})

    windows_dissolve = bool(plugin.get("enabled"))
    layers_variant = get_variant("layers", overrides.get("layers", ""))
    wants_menu_dissolve = (
        bool(layers_variant.get("layers_dissolve")) if layers_variant else preset_dissolves_menus
    )
    if wants_menu_dissolve and not windows_dissolve:
        # Menus were meant to dissolve, but windows no longer do, so the plugin
        # is off: the long 2-second fade those menus were tuned for would stay
        # and look broken. Give them a plain fade instead.
        fallback = get_variant("layers", LAYERS_FALLBACK)
        if fallback is not None:
            swap_in("layers", fallback)
        wants_menu_dissolve = False
    if windows_dissolve:
        plugin["layers"] = 1 if wants_menu_dissolve else 0
    else:
        plugin = {"enabled": 0}

    for category, speed in speeds.items():
        factor = SPEEDS.get(speed, 1.0)
        if category not in CATEGORY_LEAVES or factor == 1.0:
            continue
        fallback_spec = animations.get("global", HYPR_GLOBAL_DEFAULT)
        for leaf in MATERIALISE[category]:
            animations.setdefault(leaf, fallback_spec)
        for leaf in CATEGORY_LEAVES[category]:
            if leaf in animations:
                animations[leaf] = scale_spec(animations[leaf], factor)

    parts = [f"{c}={overrides[c]}" for c in CATEGORIES if c in overrides]
    parts += [f"{c}:{speeds[c]}" for c in CATEGORIES if speeds.get(c, "normal") != "normal"]
    composed = {
        "id": preset["id"] + ("+" + ",".join(parts) if parts else ""),
        "name": preset.get("name"),
        "beziers": beziers,
        "animations": animations,
        "dissolve": plugin,
    }
    validate(composed)
    _check_layer_durations(composed)
    return composed


def _check_layer_durations(composed):
    plugin = composed.get("dissolve") or {}
    if plugin.get("enabled") and plugin.get("layers"):
        animations = composed.get("animations") or {}
        if "fadeLayersOut" in animations or "layersOut" in animations:
            _require_same_duration(composed["id"], animations, "fadeLayersOut", "layersOut")


def menu_dissolve_available(tuning):
    """Whether menus can dissolve under this tuning: only while windows do."""
    preset = get(active_id()) or {}
    trial = {"overrides": dict(tuning.get("overrides") or {}), "speed": {}}
    trial["overrides"].pop("layers", None)
    try:
        return bool(compose(preset, trial)["dissolve"].get("enabled")) if preset else False
    except PresetError:
        return False


def current_preset():
    return get(active_id())


def apply_tuning(tuning, message):
    """Save the tuning, write the composed config, reload, say so."""
    preset = current_preset()
    if preset is None:
        notify(t("anim_no_preset"))
        return None
    composed = compose(preset, tuning)
    save_tuning(tuning)
    path = hyprconf.write(composed)
    subprocess.run(["hyprctl", "reload"], capture_output=True, check=False)
    notify(message)
    return path


def set_variant(category, variant_id):
    """Replace one category, or put it back to the preset with variant_id=None."""
    tuning = load_tuning()
    if variant_id is None:
        tuning["overrides"].pop(category, None)
        return apply_tuning(tuning, t("anim_cat_reset", category=t(CATEGORY_TITLE[category])))
    variant = get_variant(category, variant_id)
    if variant is None:
        return None
    needs_windows = category == "layers" and variant.get("layers_dissolve")
    if needs_windows and not menu_dissolve_available(tuning):
        notify(t("anim_menu_dissolve_needs_windows"))
        return None
    tuning["overrides"][category] = variant_id
    message = t(
        "anim_cat_applied",
        category=t(CATEGORY_TITLE[category]), name=_localized(variant.get("name")),
    )
    menus = get_variant("layers", tuning["overrides"].get("layers", ""))
    if category == "close" and menus and menus.get("layers_dissolve") \
            and not (variant.get("dissolve") or {}).get("enabled"):
        message += " · " + t("anim_menus_fell_back")
    return apply_tuning(tuning, message)


def set_speed(category, speed):
    tuning = load_tuning()
    if speed == "normal":
        tuning["speed"].pop(category, None)
    else:
        tuning["speed"][category] = speed
    return apply_tuning(tuning, t(
        "anim_speed_applied", category=t(CATEGORY_TITLE[category]),
        speed=t(f"anim_speed_{speed}").lower(),
    ))


def live_spec(composed, saved):
    """What to push with `hyprctl keyword` so the screen matches `composed`.

    keyword can set a leaf but never unset one, and the running config is the
    saved one. Any leaf the saved config sets but `composed` leaves to
    inheritance would keep its saved value during the demo — previewing
    "Speed: normal" would still play slow. So those leaves are set explicitly to
    what they inherit: `global`, or Hyprland's built-in default."""
    live = json.loads(json.dumps(composed))
    inherit = live["animations"].get("global", HYPR_GLOBAL_DEFAULT)
    for leaf in (saved.get("animations") or {}):
        live["animations"].setdefault(leaf, inherit)
    return live


def wait_seconds(composed, category):
    """How long the demo of one category has to wait for its animation to finish.

    Hyprland's speed is in tenths of a second; an unset leaf inherits `global`."""
    animations = composed.get("animations") or {}
    fallback = _duration(animations.get("global", HYPR_GLOBAL_DEFAULT)) or 8
    leaves = {
        "open": ("windowsIn", "fadeIn"),
        "close": ("windowsOut", "fadeOut"),
        "workspaces": ("workspaces", "specialWorkspace"),
        "layers": ("layersIn", "layersOut", "fadeLayersIn", "fadeLayersOut"),
    }[category]
    spans = [
        (_duration(animations[leaf]) or 0) if leaf in animations else fallback
        for leaf in leaves
    ]
    return round(max(spans) / 10 + 0.4, 1)


def preview_tuning(category, variant_id=None, speed=None):
    """The tuning to show live for one row: the saved tuning with that row applied."""
    tuning = load_tuning()
    tuning = {"overrides": dict(tuning["overrides"]), "speed": dict(tuning["speed"])}
    if variant_id == "-":
        tuning["overrides"].pop(category, None)
    elif variant_id:
        tuning["overrides"][category] = variant_id
    if speed:
        if speed == "normal":
            tuning["speed"].pop(category, None)
        else:
            tuning["speed"][category] = speed
    return tuning


# ─────────────────────────── rows ───────────────────────────

def preview_path(preset_id):
    return PREVIEW_DIR / f"{preset_id}.png"


def rows():
    result = [back_row(t("back"), t("back_meta"))]
    presets = load_all()
    if not presets:
        result.append(note_row(t("anim_none")))
        return result

    current = active_id()
    for preset in presets:
        pid = preset["id"]
        name = _localized(preset.get("name"))
        label = html.escape(name)
        meta = f"{name} {pid} {_localized(preset.get('description'))}"
        if pid == current:
            label += "  " + dim(MARK_ACTIVE)
            meta += f" {t('anim_active')}"
        opts = {
            "display": label,
            "meta": meta,
            "info": f"anim:{pid}",
        }
        image = preview_path(pid)
        if image.is_file():
            opts["icon"] = str(image)
        result.append((pid, opts))
    return result


# ─────────────────────────── category rows ───────────────────────────

def variant_preview_path(category, variant_id):
    return PREVIEW_DIR / category / f"{variant_id}.png"


def _with_icon(opts, image):
    if image.is_file():
        opts["icon"] = str(image)
    return opts


def category_summary(category, tuning):
    """"Spring, fast" / "as in the preset" — what the root row says about it."""
    vid = (tuning.get("overrides") or {}).get(category)
    variant = get_variant(category, vid) if vid else None
    text = _localized(variant.get("name")) if variant is not None else t("anim_as_preset").lower()
    speed = (tuning.get("speed") or {}).get(category, "normal")
    if speed != "normal":
        text += ", " + t(f"anim_speed_{speed}").lower()
    return text


def root_rows():
    """The first screen: the presets, then one row per category."""
    tuning = load_tuning()
    preset = current_preset()
    preset_name = _localized((preset or {}).get("name")) or "—"
    presets_label = t("anim_presets")
    if tuning_is_custom(tuning):
        preset_name += " · " + t("anim_customised")
    # Tiles are narrow: a second line of text gets cut to "как …". The picture
    # already shows the current choice, and the search still finds it by meta.
    result = [(presets_label, _with_icon({
        "display": html.escape(presets_label),
        "meta": f"{presets_label} presets {preset_name}",
        "info": "nav:presets",
    }, preview_path(active_id())))]

    for category in CATEGORIES:
        title = t(CATEGORY_TITLE[category])
        summary = category_summary(category, tuning)
        vid = (tuning.get("overrides") or {}).get(category)
        image = variant_preview_path(category, vid) if vid else preview_path(active_id())
        result.append((title, _with_icon({
            "display": html.escape(title),
            "meta": f"{title} {category} {summary}",
            "info": f"nav:cat:{category}",
        }, image)))
    return result


def _back(level):
    text, opts = back_row(t("back"), t("back_meta"))
    opts["info"] = f"up:{level}"  # so a preview key on it stays on this screen
    return text, _with_icon(opts, PREVIEW_DIR / "_ui" / "back.png")


def preset_rows():
    """The presets screen: a way back, then every preset."""
    return [_back("presets")] + rows()[1:]


def category_rows(category):
    """One category: back, the three speeds, "as in the preset", the variants."""
    tuning = load_tuning()
    overrides = tuning.get("overrides") or {}
    current_speed = (tuning.get("speed") or {}).get(category, "normal")
    result = [_back(f"cat:{category}")]

    # Back plus three speeds is exactly the grid's first row of four.
    for speed in SPEED_ORDER:
        label = t("anim_speed_row", speed=t(f"anim_speed_{speed}").lower())
        display = html.escape(label)
        if speed == current_speed:
            display += "  " + dim(MARK_ACTIVE)
        result.append((label, _with_icon({
            "display": display,
            "meta": f"{label} speed {speed}",
            "info": f"speed:{category}:{speed}",
        }, PREVIEW_DIR / "_ui" / f"speed-{speed}.png")))

    as_preset = t("anim_as_preset")
    display = html.escape(as_preset)
    if category not in overrides:
        display += "  " + dim(MARK_ACTIVE)
    result.append((as_preset, _with_icon({
        "display": display,
        "meta": f"{as_preset} preset reset",
        "info": f"var:{category}:-",
    }, preview_path(active_id()))))

    menu_dissolve_ok = category != "layers" or menu_dissolve_available(tuning)
    for variant in load_variants(category):
        vid = variant["id"]
        name = _localized(variant.get("name"))
        display = html.escape(name)
        if overrides.get(category) == vid:
            display += "  " + dim(MARK_ACTIVE)
        description = _localized(variant.get("description"))
        if variant.get("layers_dissolve") and not menu_dissolve_ok:
            display += "  " + dim(html.escape(t("anim_needs_window_dissolve")))
        result.append((name, _with_icon({
            "display": display,
            "meta": f"{name} {vid} {description}",
            "info": f"var:{category}:{vid}",
        }, variant_preview_path(category, vid))))
    return result
