"""The lock screen (hyprlock): a config built from a few choices. No GTK.

    backend = Backend(workers)
    info = backend.probe()               # Info: options, whether the file is ours, backup
    text = render(options, home)         # the hyprlock.conf these options give
    backend.apply(options)               # write it (the first time: back up the old file)
    backend.preview(options, out_png)    # a picture of it, drawn by simlock.py

The page edits Options (kept in ~/.config/settings-hub/lockscreen.json, no
History: nothing is applied yet); "Apply" writes ~/.config/hypr/hyprlock.conf,
one History item whose before/after are the whole file, so Ctrl+Z puts back the
file as it was, the hand-made one included.

Safety, because a broken lock screen either does not lock or cannot be left:
- the password field is always there, whatever is switched off;
- only keys the hand-made "Dock" config already used (it is known to work);
- every value is checked against a short list or a pattern; the clock and
  date formats go into `date '+…'` run by hyprlock's shell, so they are only
  ever one of CLOCKS / DATES, never typed text;
- the first apply over a file this page did not write copies it to
  ~/.config/hypr/backups/<date>-settings-hub-lock/ first;
- hyprlock is never started; the preview is ~/.local/share/hyprlock-sim/simlock.py.

Positions follow hyprlock: from the centre or an edge, the y axis UP, in
logical points (1280x720 on a 1920x1080 screen at scale 1.5).
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import subprocess
import tempfile
import threading
import time
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any

from .. import strings

log = logging.getLogger(__name__)

BACKEND = "lockscreen"
WORKER = "lockscreen"
PREVIEW_WORKER = "lockscreen-preview"
KEY = "hyprlock.conf"  # the one History key: the whole file
MARK = "# settings-hub lockscreen v1"  # first line of a file this page wrote
PREVIEW_TIMEOUT_S = 20

PRESETS = ("dock", "center", "minimal", "corner")
PARTS = ("clock", "date", "stats", "battery", "wifi", "power")
CLOCKS = ("%H:%M", "%H:%M:%S", "%-I:%M %p", "%-H:%M")
DATES = ("%A, %-d %B", "%-d %B %Y", "%a, %-d %b", "%d.%m.%Y")
CLOCK_SIZE = (40, 160)
TEXT_SIZE = (9, 22)
BLUR = (0, 4)
DIM = (30, 100)  # brightness of the wallpaper, %
FONT_NAME = re.compile(r"[\w .+-]{1,60}")
# Icons: in the plain Nerd Font they are drawn wider than a cell and hyprlock cuts them.
ICON_FONT = "JetBrainsMono Nerd Font Propo"


@dataclass
class Options:
    preset: str = "dock"
    clock: bool = True
    date: bool = True
    stats: bool = True
    battery: bool = False
    wifi: bool = False
    power: bool = True
    clock_format: str = "%H:%M"
    date_format: str = "%A, %-d %B"
    font: str = ""  # "" = $font from colors.conf
    clock_size: int = 112
    text_size: int = 13
    blur: int = 0
    dim: int = 72

    def shown(self, part: str) -> bool:
        return bool(getattr(self, part))


DEFAULTS = Options()


def clean(raw: Any) -> Options:
    """Options from a dict (the file, the page); a bad or missing value is the default."""
    out = Options()
    if not isinstance(raw, dict):
        return out
    checks = {
        "preset": lambda v: v in PRESETS,
        "clock_format": lambda v: v in CLOCKS,
        "date_format": lambda v: isinstance(v, str) and v in DATES,
        "font": lambda v: isinstance(v, str) and (v == "" or FONT_NAME.fullmatch(v)),
        "clock_size": lambda v: _int_in(v, CLOCK_SIZE),
        "text_size": lambda v: _int_in(v, TEXT_SIZE),
        "blur": lambda v: _int_in(v, BLUR),
        "dim": lambda v: _int_in(v, DIM),
        **{part: (lambda v: isinstance(v, bool)) for part in PARTS},
    }
    for key, ok in checks.items():
        if key in raw:
            if ok(raw[key]):
                setattr(out, key, raw[key])
            else:
                log.warning("lockscreen option %s: refused", key)
    return out


def _int_in(value: Any, bounds: tuple[int, int]) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) \
        and bounds[0] <= value <= bounds[1]


# ---- the layouts ---------------------------------------------------------------

@dataclass(frozen=True)
class Place:
    halign: str
    valign: str
    x: int
    y: int


@dataclass(frozen=True)
class Layout:
    clock: Place
    date: Place
    stats: Place  # the first label pair; the others follow at STAT_STEP to the side
    status: Place  # battery, then Wi-Fi under it
    input: Place
    input_size: tuple[int, int]
    power: Place | None  # the circle (the icon inside it); None: LONE_POWER
    dock: bool = False  # the glass bar under stats, field and button
    status_step: int = -24
    # How the date and the field follow the clock's size (its text box is about
    # 1.7 x the size in points tall): "below" puts the date under a centred
    # clock (and the field under the date when field_follows); "above" puts a
    # bottom-anchored clock over the date. "" keeps the places as they are.
    stack: str = ""
    field_follows: bool = False
    clock_max: int = CLOCK_SIZE[1]  # a bigger clock would run into the field


MIN_FIELD = 20  # points: a smaller password field is as good as none
STAT_STEP = 52
STAT_GAP = 26  # label above value
POWER = 50

LAYOUTS = {
    # the hand-made "Dock" of 07.11.2026, unchanged
    "dock": Layout(
        clock=Place("center", "top", 0, -92), date=Place("center", "top", 0, -72),
        stats=Place("center", "bottom", -364, 62), status=Place("right", "top", -32, -24),
        input=Place("center", "bottom", 58, 59), input_size=(516, 50),
        power=Place("center", "bottom", 369, 59), dock=True),
    "center": Layout(
        clock=Place("center", "center", 0, 130), date=Place("center", "center", 0, 0),
        stats=Place("center", "bottom", -52, 40), status=Place("right", "top", -32, -24),
        input=Place("center", "center", 0, 0), input_size=(380, 50),
        power=None, stack="below", field_follows=True),
    "minimal": Layout(
        clock=Place("center", "center", 0, 80), date=Place("center", "center", 0, 0),
        stats=Place("left", "top", 40, -48), status=Place("right", "top", -32, -24),
        input=Place("center", "bottom", 0, 80), input_size=(320, 46),
        power=None, stack="below"),
    "corner": Layout(
        clock=Place("left", "bottom", 56, 0), date=Place("left", "bottom", 62, 72),
        stats=Place("left", "top", 40, -48), status=Place("right", "top", -32, -24),
        input=Place("right", "bottom", -136, 60), input_size=(360, 50),
        power=Place("right", "bottom", -48, 60), stack="above", clock_max=104),
}
# A power button with no place of its own sits at the right end of the bottom.
LONE_POWER = Place("right", "bottom", -40, 36)


@dataclass
class Paths:
    home: Path
    conf: Path = field(init=False)
    options: Path = field(init=False)
    written: Path = field(init=False)
    backups: Path = field(init=False)
    scripts: Path = field(init=False)
    wallpaper: Path = field(init=False)
    colors: Path = field(init=False)
    simulator: Path = field(init=False)

    def __post_init__(self) -> None:
        hypr = self.home / ".config" / "hypr"
        self.conf = hypr / "hyprlock.conf"
        self.options = self.home / ".config" / "settings-hub" / "lockscreen.json"
        # sha256 of the last file this page wrote: a later hand edit is backed up
        self.written = self.home / ".config" / "settings-hub" / "lockscreen.written"
        self.backups = hypr / "backups"
        self.scripts = hypr / "scripts"
        self.wallpaper = self.home / ".local" / "state" / "hypr-wallpaper" / "lock.img"
        self.colors = hypr / "colors.conf"
        self.simulator = self.home / ".local" / "share" / "hyprlock-sim" / "simlock.py"


def _block(kind: str, lines: list[str]) -> str:
    body = "\n".join(f"    {line}" for line in ["monitor ="] + lines)
    return f"{kind} {{\n{body}\n}}\n"


def _place(p: Place, dx: int = 0, dy: int = 0) -> list[str]:
    return [f"halign = {p.halign}", f"valign = {p.valign}", f"position = {p.x + dx}, {p.y + dy}"]


def _label(text: str, color: str, size: int, font: str, place: list[str], z: int = 5,
           shadow: tuple[int, int, float] | None = None, extra: list[str] | None = None) -> str:
    lines = [f"text = {text}", f"color = {color}", f"font_size = {size}",
             f"font_family = {font}", *place, f"zindex = {z}"]
    if shadow:
        passes, size_, alpha = shadow
        lines += ["", f"shadow_passes = {passes}", f"shadow_size = {size_}",
                  f"shadow_color = rgba(0, 0, 0, {alpha})"]
    return _block("label", lines + (extra or []))


def _hooks(current: str) -> list[str]:
    """The wallpaper-theme colour line(s) of the current file, kept after colors.conf."""
    return [line for line in current.splitlines()
            if line.startswith("source") and "# wallpaper-theme" in line]


def placed(opts: Options) -> Layout:
    """The preset's layout with the date, clock and field moved for the chosen sizes."""
    lay = LAYOUTS[opts.preset]
    clock_h = round(min(opts.clock_size, lay.clock_max) * 1.7)
    text_h = round(opts.text_size * 1.75)
    clock, date, field_ = lay.clock, lay.date, lay.input
    if lay.stack == "below":
        date_y = clock.y - clock_h // 2 - 4 if opts.clock else clock.y
        date = Place(date.halign, date.valign, date.x, date_y)
        if lay.field_follows:
            under = date_y - (text_h // 2 + 44 if opts.date else lay.input_size[1] // 2 + 16)
            field_ = Place(field_.halign, field_.valign, field_.x, under)
    elif lay.stack == "above":
        clock_y = date.y + (text_h if opts.date else 0)
        clock = Place(clock.halign, clock.valign, clock.x, clock_y)
    return replace(lay, clock=clock, date=date, input=field_)


def render(opts: Options, paths: Paths, current: str = "") -> str:
    """hyprlock.conf for these options; `current` gives the wallpaper-theme hook to keep."""
    lay = placed(opts)
    font = opts.font or "$font"
    out = [
        MARK,
        "# " + strings.LOCK_CONF_HEADER,
        f"# {paths.options}",
        "",
        "source = ~/.config/hypr/colors.conf",
        *_hooks(current),
        "",
        "general {\n    hide_cursor = false\n}\n",
        "animations {\n    enabled = true\n"
        "    bezier = premiumEase, 0.16, 1.0, 0.3, 1.0\n"
        "    animation = fadeIn, 0\n"
        "    animation = fadeOut, 1, 5, premiumEase\n"
        "    animation = inputFieldColors, 1, 4, premiumEase\n"
        "    animation = inputFieldFade, 1, 4, premiumEase\n"
        "    animation = inputFieldWidth, 1, 4, premiumEase\n"
        "    animation = inputFieldDots, 1, 3, premiumEase\n}\n",
        _block("background", [
            f"path = {paths.wallpaper}", "color = $c_black", "",
            f"blur_passes = {opts.blur}", "blur_size = 10", "noise = 0.012",
            "contrast = 1.0", f"brightness = {opts.dim / 100:.2f}", "vibrancy = 0.2",
            "vibrancy_darkness = 0.0"]),
    ]
    if opts.date:
        out.append(_label(f"cmd[update:60000] date '+{opts.date_format}' | sed 's/^./\\U&/'",
                          "$c_grey_light", opts.text_size, font, _place(lay.date),
                          shadow=(1, 6, 0.4)))
    if opts.clock:
        text = "$TIME" if opts.clock_format == "%H:%M" else \
            f"cmd[update:1000] date '+{opts.clock_format}'"
        out.append(_label(text, "$c_white", min(opts.clock_size, lay.clock_max), font,
                          _place(lay.clock),
                          shadow=(2, 16, 0.35)))
    if lay.dock:
        out.append(_block("shape", [
            "size = 820, 80", "rounding = 40", "color = $c_dock_panel", "border_size = 1",
            "border_color = $c_dock_border", "halign = center", "valign = bottom",
            "position = 0, 44", "zindex = 2", "", "shadow_passes = 3", "shadow_size = 24",
            "shadow_color = rgba(0, 0, 0, 0.45)"]))
    if opts.stats:
        small = max(opts.text_size - 5, 7)
        value = max(opts.text_size - 2, 8)
        step = STAT_STEP if lay.stats.halign != "right" else -STAT_STEP
        scripts = (
            ("CPU", f"cmd[update:2000] {paths.scripts / 'lock-status-cpu.sh'}"),
            ("RAM", f"cmd[update:3000] {paths.scripts / 'lock-status-ram.sh'}"
                    " | sed -E 's/.*\\(([0-9]+%)\\).*/\\1/'"),
            ("TEMP", f"cmd[update:5000] {paths.scripts / 'lock-status-temp.sh'}"
                     " | sed -E 's/^([0-9]+)([.,][0-9]+)?°C$/\\1°/'"),
        )
        for index, (name, command) in enumerate(scripts):
            # TEMP 2 points right in the dock, as in the hand-made one
            dx = index * step + (2 if name == "TEMP" and lay.dock else 0)
            out.append(_label(name, "$c_grey_label", small, font,
                              _place(lay.stats, dx, STAT_GAP), z=4))
            out.append(_label(command, "$c_white", value, font, _place(lay.stats, dx), z=4))
        if lay.dock:
            out.append(_block("shape", [
                "size = 1, 36", "rounding = 0", "color = $c_dock_border", "border_size = 0",
                "halign = center", "valign = bottom", "position = -226, 66", "zindex = 3"]))
    status = 0
    for part, script in (("battery", "lock-status-battery.sh"), ("wifi", "lock-status-wifi.sh")):
        if opts.shown(part):
            out.append(_label(f"cmd[update:10000] {paths.scripts / script}", "$c_grey_light",
                              max(opts.text_size - 2, 8), font,
                              _place(lay.status, 0, status * lay.status_step), z=4))
            status += 1
    w, h = lay.input_size
    out.append(_block("input-field", [
        f"size = {w}, {h}", "rounding = -1", "outline_thickness = 2", "dots_size = 0.26",
        "dots_spacing = 0.3", "dots_center = true", "dots_rounding = -1", "",
        "inner_color = $c_glass_fill", "outer_color = $c_input_ring",
        "font_color = $c_white", f"font_family = {font}", "",
        "capslock_color = $c_caps_ring", "numlock_color = $c_num_ring",
        "bothlock_color = $c_both_ring", "invert_numlock = false", "",
        "check_color = $c_check_ring", "fail_color = $c_fail_ring",
        f"fail_text = <i>{strings.LOCK_CONF_FAIL} ($ATTEMPTS)</i>", "fail_timeout = 1500",
        "fail_transition = 250", "",
        f"placeholder_text = {strings.LOCK_CONF_PLACEHOLDER}", "fade_on_empty = false",
        "hide_input = false", "", *_place(lay.input), "zindex = 4"]))
    if opts.power:
        place = lay.power or LONE_POWER
        out.append(_block("shape", [
            f"size = {POWER}, {POWER}", "rounding = -1", "color = $c_glass_fill",
            "border_size = 1", "border_color = $c_dock_border", *_place(place), "zindex = 4",
            "onclick = systemctl poweroff"]))
        icon_dx = 0 if place.halign == "center" else (-16 if place.halign == "right" else 16)
        out.append(_label("⏻", "$c_white", 14, ICON_FONT, _place(place, icon_dx, 14),
                          extra=["onclick = systemctl poweroff"]))
    text = "\n".join(out).rstrip() + "\n"
    check(text)
    return text


def check(text: str) -> None:
    """ValueError unless the file can still be left: one real password field.

    Lines are read without comments: the field's block must open on a line of
    its own, close, and give a plain size of at least MIN_FIELD points (or 2 %)
    on both sides.
    """
    for line in text.splitlines():
        if any(ord(c) < 32 and c != "\t" for c in line):
            raise ValueError("control characters")
    body = [line.split("#", 1)[0].strip() for line in text.splitlines()]
    starts = [i for i, line in enumerate(body) if re.fullmatch(r"input-field\s*\{", line)]
    if len(starts) != 1:
        raise ValueError("a lock screen needs exactly one password field")
    for line in body[starts[0] + 1:]:
        if line == "}":
            break
        if line.split("=", 1)[0].strip() == "size":
            size = re.fullmatch(r"size\s*=\s*(\d+)(%?)\s*,\s*(\d+)(%?)", line)
            if not size:
                raise ValueError("the password field size is not plain numbers")
            for value, pct in ((size.group(1), size.group(2)), (size.group(3), size.group(4))):
                if int(value) < (2 if pct else MIN_FIELD):  # 2 % or 20 points, each side
                    raise ValueError("the password field is too small to see")
    else:
        raise ValueError("the password field block is not closed")


def is_ours(text: str) -> bool:
    return text.startswith(MARK)


# ---- the backend -----------------------------------------------------------------

@dataclass
class Info:
    options: Options
    found: bool  # hyprlock.conf exists
    ours: bool  # this page wrote it
    backup: str  # where the hand-made file was copied, "" if nowhere yet
    simulator: bool  # the preview can be drawn
    applied: bool  # the file is what the options give
    theme_font: str = ""  # $font of colors.conf: what "" means
    colors: bool = True  # colors.conf is there (apply refuses without it)
    edited: bool = False  # written here, then changed by hand (Apply backs it up)


class Backend:
    def __init__(self, workers, home: Path | None = None) -> None:
        self.workers = workers
        self.paths = Paths(home or Path.home())
        self._lock = threading.Lock()

    # ---- options (no History: nothing is applied by them) ----------------------

    def load_options(self) -> Options:
        try:
            return clean(json.loads(self.paths.options.read_text(encoding="utf-8")))
        except FileNotFoundError:
            return Options()
        except (OSError, ValueError) as exc:
            log.warning("lockscreen options: %s", exc)
            return Options()

    def save_options(self, opts: Options) -> None:
        _write(self.paths.options, json.dumps(asdict(opts), ensure_ascii=False, indent=1) + "\n")

    # ---- reading ----------------------------------------------------------------

    def current(self) -> str:
        try:
            return self.paths.conf.read_text(encoding="utf-8")
        except FileNotFoundError:
            return ""

    def backup_path(self) -> Path | None:
        """The newest copy of a hand-made file: what "Restore" puts back."""
        return self._newest("lock")

    def _newest(self, kind: str) -> Path | None:
        """Newest copy by time written (names can tie); "edit" = an edited generated file."""
        found = []
        for path in self.paths.backups.glob(f"*-settings-hub-{kind}/hyprlock.conf"):
            try:
                found.append((path.stat().st_mtime_ns, path.parent.name, path))
            except OSError:  # a dangling link: not a copy
                continue
        return max(found)[2] if found else None

    def probe(self) -> Info:
        opts = self.load_options()
        text = self.current()
        backup = self.backup_path()
        try:
            applied = bool(text) and render(opts, self.paths, text) == text
        except ValueError:
            applied = False
        return Info(opts, bool(text), is_ours(text), str(backup or ""),
                    self.paths.simulator.is_file(), applied, self.theme_font(),
                    self.paths.colors.is_file(),
                    bool(text) and is_ours(text) and self.hand_made(text))

    def theme_font(self) -> str:
        try:
            text = self.paths.colors.read_text(encoding="utf-8")
        except OSError:
            return ""
        found = re.search(r"^\$font\s*=\s*(.+?)\s*$", text, re.M)
        return found.group(1) if found else ""

    def read(self, keys: list[str]) -> dict[str, Any]:
        return {KEY: self.current()} if KEY in keys else {}

    # ---- writing -----------------------------------------------------------------

    def apply(self, opts: Options) -> tuple[str, str]:
        """Write the file these options give; (before, after). Backs up a hand-made one."""
        with self._lock:
            before = self.current()
            if not self.paths.colors.is_file():  # every colour and $font come from it
                raise ValueError(f"{self.paths.colors} is missing")
            after = render(opts, self.paths, before)
            if before and self.hand_made(before):
                self._back_up(before)
            if after != before:
                self._write_conf(after)
            return before, after

    def hand_made(self, text: str) -> bool:
        """Not written by this page, or written and then edited by hand."""
        if not is_ours(text):
            return True
        try:
            written = self.paths.written.read_text(encoding="utf-8").strip()
        except OSError:
            return False  # ours, and no record to compare with
        return written != _digest(text)

    def _back_up(self, text: str) -> None:
        # A generated file edited by hand is kept apart: "Restore" stays the hand-made one.
        kind = "edit" if is_ours(text) else "lock"
        last = self._newest(kind)
        if last is not None and last.read_text(encoding="utf-8") == text:
            return  # this very text is saved already
        stamp = time.strftime("%Y-%m-%d-%H%M%S")
        folder = self.paths.backups / f"{stamp}-settings-hub-{kind}"
        n = 1
        while folder.exists():
            folder = self.paths.backups / f"{stamp}-{n}-settings-hub-{kind}"
            n += 1
        folder.mkdir(parents=True)
        try:  # the copy as private as the file
            mode = self.paths.conf.stat().st_mode & 0o777
        except OSError:
            mode = 0o600
        _write(folder / "hyprlock.conf", text, mode)
        log.info("lock screen backed up to %s", folder)

    def _write_conf(self, text: str) -> None:
        _write(self.paths.conf, text)
        try:
            _write(self.paths.written, _digest(text) + "\n")
        except OSError as exc:  # the file is written; only a later hand edit goes unnoticed
            log.warning("could not record the lock screen written: %s", exc)

    def write_text(self, text: str) -> None:
        """History's undo/redo: the whole file back as it was (still checked)."""
        if not text:
            raise ValueError("an empty lock screen config is not written")
        check(text)
        with self._lock:
            self._write_conf(text)

    def apply_values(self, values: dict[str, Any]) -> None:  # History applier
        if KEY in values:
            self.write_text(values[KEY])

    def restore_backup(self) -> tuple[str, str]:
        backup = self.backup_path()
        if backup is None:
            raise FileNotFoundError("no backup")
        text = backup.read_text(encoding="utf-8")
        with self._lock:
            before = self.current()
        self.write_text(text)
        return before, text

    # ---- the picture ---------------------------------------------------------------

    def preview(self, opts: Options, out: Path) -> Path:
        """Draw the lock screen these options give into out (PNG); RuntimeError on failure."""
        if not self.paths.simulator.is_file():
            raise RuntimeError("the simulator is not installed")
        out.parent.mkdir(parents=True, exist_ok=True)
        conf = out.with_suffix(".conf")
        conf.write_text(render(opts, self.paths, self.current()), encoding="utf-8")
        part = out.with_name(out.stem + ".part.png")  # the page never reads half a picture
        part.unlink(missing_ok=True)  # a leftover from a killed run is not a new picture
        argv = ["python3", "-I", str(self.paths.simulator), str(conf), str(part)]
        if self.paths.wallpaper.exists():
            argv += ["--wall", str(self.paths.wallpaper)]
        env = dict(os.environ, TMPDIR=str(out.parent))
        try:
            done = subprocess.run(argv, capture_output=True, text=True, env=env,
                                  timeout=PREVIEW_TIMEOUT_S, check=False)
        except (OSError, subprocess.TimeoutExpired) as exc:
            raise RuntimeError(str(exc)) from exc
        if done.returncode != 0 or not part.exists():
            raise RuntimeError((done.stderr.strip().splitlines() or ["?"])[-1])
        os.replace(part, out)
        return out


def _write(path: Path, text: str, mode: int | None = None) -> None:
    """Atomic write that keeps the mode (or sets mode) and writes through a symlink."""
    path = path.resolve() if path.is_symlink() else path
    path.parent.mkdir(parents=True, exist_ok=True)
    if mode is None:
        try:
            mode = path.stat().st_mode & 0o7777
        except FileNotFoundError:
            mode = 0o644
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            fh.write(text)
            fh.flush()
            os.fsync(fh.fileno())  # a lock screen file must not come back empty after a crash
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


def _digest(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class Applier:
    backend = BACKEND

    def __init__(self, backend: Backend) -> None:
        self.b = backend

    def read(self, keys: list[str]) -> dict[str, Any]:
        return self.b.read(keys)

    def apply(self, values: dict[str, Any]) -> None:
        self.b.apply_values(values)


def register(history, backend: Backend) -> Applier:
    applier = Applier(backend)
    history.register(BACKEND, applier)
    return applier
