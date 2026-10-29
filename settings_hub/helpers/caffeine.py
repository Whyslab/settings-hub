"""Turn screen-sleep's "stay awake" mode on or off, then exit.

    python3 -I caffeine.py on|off [--dir SCREEN_SLEEP_DIR]

Run as a short separate process, not inside the resident window:
idle.caffeine_set() starts systemd-inhibit as a child of its caller and does
not wait for it when switching off, so a long-running caller would collect
zombies. Here the helper exits right away and systemd-inhibit (started in its
own session) is re-parented.

Self-contained on purpose: under -I there is no script directory and no
settings_hub package on the path, so nothing is imported from the package. The
live common.py and idle.py are loaded by absolute path; for the duration of the
load `common` is aliased in sys.modules, because idle.py does
`from common import ...`. No byte-code is written into that directory.

Exit status 0 on success; otherwise 1 with the reason on stderr.
"""

import importlib.util
import os
import sys
from pathlib import Path


def default_dir() -> Path:
    return Path.home() / ".local" / "share" / "screen-sleep"


def load(directory: Path, name: str):
    path = directory / f"{name}.py"
    spec = importlib.util.spec_from_file_location(f"_ss_helper.{name}", path)
    if spec is None or spec.loader is None:
        raise ImportError(f"cannot load {path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module  # alias for `from common import ...`
    spec.loader.exec_module(module)
    return module


def main(argv: list[str]) -> int:
    if len(argv) not in (1, 3) or argv[0] not in ("on", "off") or (
            len(argv) == 3 and argv[1] != "--dir"):
        print("usage: caffeine.py on|off [--dir DIR]", file=sys.stderr)
        return 2
    directory = Path(argv[2]) if len(argv) == 3 else default_dir()
    if not directory.is_absolute():
        directory = Path(os.getcwd()) / directory
    sys.dont_write_bytecode = True
    try:
        load(directory, "common")
        idle = load(directory, "idle")
    except Exception as exc:
        print(f"screen-sleep modules: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    ok, message = idle.caffeine_set(argv[0] == "on")
    if not ok:
        print(message, file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
