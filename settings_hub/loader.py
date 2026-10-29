"""Load the live modules of other projects by file path, under private names.

screen-sleep ships flat modules (common.py, idle.py, night.py) that import each
other as top-level names (`from common import ...`). Putting their directory on
sys.path would make `common`, `idle` and `night` global names in this process
and could shadow anything else called that. So each file is loaded with
importlib under a private name (_ss_live.common, ...); for the duration of the
load only, `common`/`idle`/`night` are aliased in sys.modules so the modules'
own imports resolve, and the aliases are removed afterwards.

One consequence: common.load_config() lazily runs `from idle import ...` when
config.json does not exist yet (it migrates an old config). That import would
fail after the aliases are gone, so callers must check config_exists() first
and never call load_config() without a config file.

The rofi hub is a real package with relative imports; it is imported as
_rofi_live.rofi_hub from the installed directory.

Loading never writes byte-code caches into the other project's directory:
those files belong to that project, not to us.

Paths come from arguments, else from environment variables (so tests and
sandboxes can point at copies), else from the default install locations.
"""

from __future__ import annotations

import importlib
import importlib.util
import os
import sys
import types
from dataclasses import dataclass
from pathlib import Path

SS_PACKAGE = "_ss_live"
SS_MODULES = ("common", "idle", "night")  # load order: idle and night import common
ROFI_PACKAGE = "_rofi_live"


class LoadError(Exception):
    pass


def screen_sleep_dir() -> Path:
    env = os.environ.get("SETTINGS_HUB_SCREEN_SLEEP_DIR")
    return Path(env) if env else Path.home() / ".local" / "share" / "screen-sleep"


def rofi_dir() -> Path:
    env = os.environ.get("SETTINGS_HUB_ROFI_DIR")
    return Path(env) if env else Path.home() / ".local" / "share" / "rofi-launcher"


@dataclass(frozen=True)
class ScreenSleep:
    common: types.ModuleType
    idle: types.ModuleType
    night: types.ModuleType
    directory: Path
    mtimes: dict[str, float]

    def config_exists(self) -> bool:
        return Path(self.common.CONFIG_FILE).exists()

    def changed_on_disk(self) -> bool:
        return _mtimes(self.directory, SS_MODULES) != self.mtimes


def _mtimes(directory: Path, names: tuple[str, ...]) -> dict[str, float]:
    out = {}
    for name in names:
        try:
            out[name] = (directory / f"{name}.py").stat().st_mtime
        except OSError:
            out[name] = -1.0
    return out


def _package(name: str, path: list[str]) -> types.ModuleType:
    pkg = types.ModuleType(name)
    pkg.__path__ = path
    pkg.__package__ = name
    sys.modules[name] = pkg
    return pkg


def load_screen_sleep(directory: Path | str | None = None) -> ScreenSleep:
    directory = Path(directory) if directory else screen_sleep_dir()
    for name in SS_MODULES:
        if not (directory / f"{name}.py").is_file():
            raise LoadError(f"{directory / name}.py not found")
    mtimes = _mtimes(directory, SS_MODULES)
    saved = {name: sys.modules.get(name) for name in SS_MODULES}
    # A fresh private package each time: reloading after an update gets new code.
    for name in [m for m in sys.modules if m == SS_PACKAGE or m.startswith(SS_PACKAGE + ".")]:
        del sys.modules[name]
    pkg = _package(SS_PACKAGE, [])
    loaded: dict[str, types.ModuleType] = {}
    no_pyc = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        for name in SS_MODULES:
            full = f"{SS_PACKAGE}.{name}"
            spec = importlib.util.spec_from_file_location(full, directory / f"{name}.py")
            if spec is None or spec.loader is None:
                raise LoadError(f"cannot load {directory / name}.py")
            module = importlib.util.module_from_spec(spec)
            sys.modules[full] = module
            sys.modules[name] = module  # temporary alias for `from common import ...`
            spec.loader.exec_module(module)
            setattr(pkg, name, module)
            loaded[name] = module
    except LoadError:
        raise
    except Exception as exc:
        raise LoadError(f"{type(exc).__name__}: {exc}") from exc
    finally:
        sys.dont_write_bytecode = no_pyc
        for name, previous in saved.items():
            if previous is None:
                sys.modules.pop(name, None)
            else:
                sys.modules[name] = previous
    return ScreenSleep(loaded["common"], loaded["idle"], loaded["night"], directory, mtimes)


def load_rofi_module(dotted: str, directory: Path | str | None = None) -> types.ModuleType:
    """Import e.g. "rofi_hub.sections.animations" from the installed hub."""
    directory = Path(directory) if directory else rofi_dir()
    if not (directory / dotted.split(".")[0] / "__init__.py").is_file():
        raise LoadError(f"{directory / dotted.split('.')[0]} is not a package")
    pkg = sys.modules.get(ROFI_PACKAGE)
    if pkg is None or list(getattr(pkg, "__path__", [])) != [str(directory)]:
        for name in [m for m in sys.modules
                     if m == ROFI_PACKAGE or m.startswith(ROFI_PACKAGE + ".")]:
            del sys.modules[name]
        _package(ROFI_PACKAGE, [str(directory)])
    no_pyc = sys.dont_write_bytecode
    sys.dont_write_bytecode = True
    try:
        return importlib.import_module(f"{ROFI_PACKAGE}.{dotted}")
    except Exception as exc:
        raise LoadError(f"{type(exc).__name__}: {exc}") from exc
    finally:
        sys.dont_write_bytecode = no_pyc
