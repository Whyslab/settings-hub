"""Hyprland variables: read live with getoption, change with keyword, persist in Lua.

Two sources of truth, and they are different on purpose:

* the live session (`hyprctl getoption` / `hyprctl keyword`) -- what the pages
  show and change, so the window always reflects what Hyprland really uses;
* a small state file and the generated `~/.config/hypr/settings-hub-vars.lua`
  -- what survives `hyprctl reload` and a new login. Only values a person
  changed are kept there; everything else still comes from the person's own
  hyprland.lua.

`settings-hub.lua` loads that file last (the installer puts one `dofile` line
in it), so later assignments win. Nothing in hyprland.lua is ever edited.

The cursor theme and size are not Hyprland options: they live in the
environment, so they are written as `hl.env(...)` lines and applied to running
clients with `hyprctl setcursor` (already-open windows keep the old cursor
until they are restarted -- that is how the compositor works).

No GTK here.
"""

from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..workers import Workers
from . import VARS, Var

log = logging.getLogger(__name__)

BACKEND = "hypr"  # History name for every variable
WORKER = "hypr-vars"
WORKER_READ = "hypr-vars-read"

CURSOR_DIRS = (Path("/usr/share/icons"), Path("/usr/local/share/icons"),
               Path.home() / ".local" / "share" / "icons",
               Path.home() / ".icons")
DEFAULT_CURSOR = "Bibata-Modern-Classic"

Result = tuple[int, str, str]  # returncode, stdout, stderr
Runner = Callable[[list[str]], Result]


def _run(argv: list[str]) -> Result:
    try:
        done = subprocess.run(argv, capture_output=True, text=True, timeout=5,
                              check=False)
    except (OSError, subprocess.SubprocessError) as exc:
        return 127, "", str(exc)
    return done.returncode, done.stdout, done.stderr


def state_path() -> Path:
    base = os.environ.get("XDG_STATE_HOME") or str(Path.home() / ".local" / "state")
    return Path(base) / "settings-hub" / "hyprvars.json"


def lua_path() -> Path:
    base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "hypr" / "settings-hub-vars.lua"


@dataclass(frozen=True)
class ApplyResult:
    ok: bool
    message: str = ""
    values: dict[str, Any] = None  # values that really changed, read back

    def __post_init__(self) -> None:
        if self.values is None:
            object.__setattr__(self, "values", {})


def parse_getoption(text: str, var: Var | None = None) -> Any:
    """The live value from `hyprctl getoption -j` output.

    getoption answers with one typed key: int, float, bool, str, css (an
    option with several per-side values, like gaps: "6 6 6 6") or vec2.
    """
    try:
        raw = json.loads(text)
    except ValueError:
        raise ValueError(f"getoption: not JSON: {text[:80]!r}") from None
    if not isinstance(raw, dict):
        raise ValueError(f"getoption: not an object: {text[:80]!r}")
    if "int" in raw:
        value: Any = int(raw["int"])
    elif "float" in raw:
        value = round(float(raw["float"]), 4)
    elif "bool" in raw:
        value = bool(raw["bool"])
    elif "str" in raw:
        value = str(raw["str"])
        if value == "[[EMPTY]]":
            value = ""
    elif "css" in raw:
        parts = str(raw["css"]).split()
        value = int(parts[0]) if parts else 0
    elif "vec2" in raw:
        value = raw["vec2"]
    else:
        raise ValueError(f"getoption: no value in {text[:80]!r}")
    if var is not None:
        if var.kind == "choice":
            value = str(value)
        elif var.kind == "float":
            value = float(value)
        elif var.kind == "int":
            value = int(value)
        elif var.kind == "bool":
            value = bool(value)
    return value


def keyword_text(var: Var, value: Any) -> str:
    """How a value is written for `hyprctl keyword`."""
    if var.kind == "bool":
        return "true" if value else "false"
    if var.kind == "float":
        return f"{float(value):.4f}".rstrip("0").rstrip(".")
    if var.kind == "choice" and var.numeric_choice:
        return str(int(value))
    return str(value)


def build_lua(values: dict[str, Any]) -> str:
    """The managed Lua file: hl.config(...) for options, hl.env(...) for cursor."""
    config: dict[str, Any] = {}
    cursor: dict[str, Any] = {}
    for option, value in values.items():
        var = next((v for v in VARS if v.option == option), None)
        if var is None:
            continue
        if var.special:
            cursor[option] = value
            continue
        node = config
        path = var.lua_path
        for part in path[:-1]:
            node = node.setdefault(part, {})
        node[path[-1]] = var.stored(value)
    lines = [
        "-- Generated by settings-hub: the values changed in the Settings window.",
        "-- The window rewrites this file; load it last (settings-hub.lua does).",
    ]
    if config:
        lines.append("hl.config(" + _lua_table(config, 0) + ")")
    if "cursor:theme" in cursor:
        lines.append(f"hl.env(\"XCURSOR_THEME\", {json.dumps(str(cursor['cursor:theme']))})")
    if "cursor:size" in cursor:
        size = int(cursor["cursor:size"])
        lines.append(f'hl.env("XCURSOR_SIZE", {json.dumps(str(size))})')
    return "\n".join(lines) + "\n"


def _lua_table(node: dict[str, Any], depth: int) -> str:
    pad = "    " * (depth + 1)
    end = "    " * depth
    parts = []
    for key in sorted(node):
        value = node[key]
        if isinstance(value, dict):
            parts.append(f"{pad}{key} = {_lua_table(value, depth + 1)},")
        else:
            parts.append(f"{pad}{key} = {_lua(value)},")
    return "{\n" + "\n".join(parts) + "\n" + end + "}"


def _lua(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        if isinstance(value, float):
            return repr(round(value, 6))
        return str(value)
    return json.dumps(str(value), ensure_ascii=False)


class Backend:
    """Reads, applies and remembers the variables. All slow work on workers."""

    def __init__(self, workers: Workers, runner: Runner | None = None,
                 state: Path | str | None = None, lua: Path | str | None = None,
                 env: dict[str, str] | None = None,
                 cursor_dirs: Iterable[Path] = CURSOR_DIRS) -> None:
        self.workers = workers
        self.run = runner or _run
        self.state = Path(state) if state is not None else state_path()
        self.lua = Path(lua) if lua is not None else lua_path()
        self.env = dict(env if env is not None else os.environ)
        self.cursor_dirs = tuple(cursor_dirs)

    # ---- reading ---------------------------------------------------------

    def read_one(self, option: str) -> Any:
        var = next((v for v in VARS if v.option == option), None)
        if var is None:
            raise RuntimeError(f"unknown variable {option}")
        if var.special:
            return self._read_cursor(var)
        code, out, err = self.run(["hyprctl", "getoption", option, "-j"])
        if code != 0:
            raise RuntimeError(err.strip() or out.strip() or "getoption failed")
        return parse_getoption(out, var)

    def _read_cursor(self, var: Var) -> Any:
        values = self._stored()
        if var.option in values:
            return values[var.option]
        if var.option == "cursor:theme":
            return self.env.get("XCURSOR_THEME") or DEFAULT_CURSOR
        try:
            return int(self.env.get("XCURSOR_SIZE") or 24)
        except ValueError:
            return 24

    def read_all(self) -> dict[str, Any]:
        """Every variable's live value; one bad option does not hide the rest."""
        out: dict[str, Any] = {}
        for var in VARS:
            try:
                out[var.option] = self.read_one(var.option)
            except (RuntimeError, ValueError) as exc:
                log.warning("reading %s: %s", var.option, exc)
        return out

    def queue_read_all(self, on_done: Callable[[dict[str, Any], BaseException | None],
                                               None]) -> None:
        self.workers.submit(WORKER_READ, self.read_all, on_done)

    # ---- changing --------------------------------------------------------

    def cursor_themes(self) -> list[str]:
        """Installed cursor themes, by the directories Hyprland looks in."""
        names: list[str] = []
        for directory in self.cursor_dirs:
            try:
                children = sorted(directory.iterdir())
            except OSError:
                continue
            for child in children:
                if (child / "cursors").is_dir() and child.name not in names:
                    names.append(child.name)
        if not names:
            names.append(DEFAULT_CURSOR)
        return names

    def apply_now(self, values: dict[str, Any], read_back: bool = True) -> ApplyResult:
        """Change the live session, then remember the values in the Lua file.

        Everything runs on the caller's thread: the page calls it through a
        worker, History calls it directly when undoing.
        """
        errors: list[str] = []
        changed: dict[str, Any] = {}
        cursor_changed = False
        for option, value in values.items():
            var = next((v for v in VARS if v.option == option), None)
            if var is None:
                continue
            if var.special:
                cursor_changed = True
                continue
            code, out, err = self.run(["hyprctl", "keyword", option,
                                       keyword_text(var, value)])
            text = (out + err).strip()
            if code != 0 or text.lower().startswith(("error", "keyword: invalid",
                                                     "invalid", "unknown")):
                errors.append(f"{option}: {text or f'exit {code}'}")
                continue
            changed[option] = value
        if cursor_changed:
            ok, message = self._apply_cursor(values, changed)
            if not ok:
                errors.append(message)
        if changed:
            stored = self._stored()
            stored.update(changed)
            self._save(stored)
            self._write_lua(stored)
            if read_back:
                for option, value in list(changed.items()):
                    try:
                        live = self.read_one(option)
                    except (RuntimeError, ValueError):
                        continue
                    if live != value and not _close(live, value):
                        changed[option] = live  # what Hyprland really did
        if errors:
            return ApplyResult(False, "; ".join(errors), changed)
        return ApplyResult(True, "", changed)

    def _apply_cursor(self, values: dict[str, Any],
                      changed: dict[str, Any]) -> tuple[bool, str]:
        stored = self._stored()
        theme = values.get("cursor:theme", stored.get("cursor:theme")
                           or self.env.get("XCURSOR_THEME") or DEFAULT_CURSOR)
        try:
            size = int(values.get("cursor:size", stored.get("cursor:size")
                                  or self.env.get("XCURSOR_SIZE") or 24))
        except (TypeError, ValueError):
            size = 24
        code, out, err = self.run(["hyprctl", "setcursor", str(theme), str(size)])
        text = (out + err).strip()
        if code != 0:
            return False, f"setcursor: {text or f'exit {code}'}"
        if "cursor:theme" in values:
            changed["cursor:theme"] = str(theme)
        if "cursor:size" in values:
            changed["cursor:size"] = size
        return True, ""

    def reload(self) -> tuple[bool, str]:
        """Read the config files again: a change in the managed Lua file lands now."""
        code, out, err = self.run(["hyprctl", "reload"])
        text = (out + err).strip()
        return code == 0 and "error" not in text.lower(), text

    def clear(self, options: Iterable[str]) -> ApplyResult:
        """Forget the window's values for these options (the config decides again)."""
        stored = self._stored()
        removed = [o for o in options if stored.pop(o, None) is not None]
        if not removed:
            return ApplyResult(True)
        self._save(stored)
        self._write_lua(stored)
        return ApplyResult(True, "", {})

    def queue_apply(self, values: dict[str, Any],
                     on_done: Callable[[ApplyResult, BaseException | None], None]) -> None:
        self.workers.submit(WORKER, lambda: self.apply_now(values), on_done)

    # ---- History's view --------------------------------------------------

    def read(self, keys: list[str]) -> dict[str, Any]:
        out: dict[str, Any] = {}
        for key in keys:
            if not any(v.option == key for v in VARS):
                continue
            try:
                out[key] = self.read_one(key)
            except (RuntimeError, ValueError) as exc:
                log.warning("reading %s: %s", key, exc)
        return out

    def apply(self, values: dict[str, Any]) -> None:
        result = self.apply_now(values, read_back=False)
        if not result.ok:
            raise RuntimeError(result.message)

    # ---- files -----------------------------------------------------------

    def _stored(self) -> dict[str, Any]:
        try:
            raw = json.loads(self.state.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {}
        except (OSError, ValueError) as exc:
            log.warning("variables %s: %s", self.state, exc)
            return {}
        if not isinstance(raw, dict):
            return {}
        known = {v.option for v in VARS}
        return {k: v for k, v in raw.items() if k in known}

    def _save(self, values: dict[str, Any]) -> None:
        text = json.dumps(values, ensure_ascii=False, indent=1, sort_keys=True) + "\n"
        _atomic_write(self.state, text)

    def _write_lua(self, values: dict[str, Any]) -> None:
        _atomic_write(self.lua, build_lua(values))


def _close(a: Any, b: Any) -> bool:
    try:
        return abs(float(a) - float(b)) < 1e-3
    except (TypeError, ValueError):
        return False


def _atomic_write(path: Path, text: str) -> None:
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(text)
            os.replace(tmp, path)
        except BaseException:
            Path(tmp).unlink(missing_ok=True)
            raise
    except OSError as exc:  # a read-only config dir must not break the page
        log.warning("writing %s: %s", path, exc)


def register(history, backend: Backend):
    """History works on single variables; adding more needs `register_many`."""
    history.register(BACKEND, backend)
    return backend


def hyprctl_available() -> bool:
    return shutil.which("hyprctl") is not None
