"""Key capture's fallback: an empty submap with a watchdog. No GTK.

Hyprland handles its own binds before the window sees the keys. The window
first asks for the keyboard-shortcuts inhibitor (widgets/keycapture.py); if the
compositor does not grant it within 300 ms, this fallback runs:

1. a fresh random token goes into $XDG_RUNTIME_DIR/settings-hub-capture;
2. `hyprctl dispatch submap settings-hub-capture` - an empty submap, so every
   key reaches the window (its one bind, SUPER CTRL ALT Escape, resets it);
3. at once, `hyprctl dispatch exec <watchdog>`: Hyprland starts the watchdog,
   so it lives apart from the window and still runs if the window crashes.
   After 15 s it resets the submap only if the token file still holds *its*
   token (no newer capture began) and `hyprctl submap` still reports
   settings-hub-capture (nobody switched elsewhere); otherwise it does nothing.

After the capture the window deletes its token and resets the submap itself.
The fallback is used only when Hyprland reports the submap in `hyprctl binds
-j` (settings-hub.conf defines it with its one way out); otherwise the capture
goes on without it.
"""

from __future__ import annotations

import json
import os
import secrets
import shlex
from pathlib import Path

from .writer import Runner

SUBMAP = "settings-hub-capture"
TOKEN_FILE = "settings-hub-capture"
WATCHDOG_S = 15


def token_path(runtime_dir: Path | str | None = None) -> Path:
    base = runtime_dir or os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(base) / TOKEN_FILE


def watchdog_command(path: Path, token: str, seconds: int | float = WATCHDOG_S) -> str:
    """The shell command Hyprland runs (`exec` hands it to sh -c)."""
    return (f"sleep {seconds}; "
            f'[ "$(cat {shlex.quote(str(path))} 2>/dev/null)" = {token} ] && '
            f'[ "$(hyprctl submap)" = {SUBMAP} ] && '
            f"hyprctl dispatch submap reset")


class SubmapFallback:
    def __init__(self, hyprctl: Runner, runtime_dir: Path | str | None = None,
                 seconds: int | float = WATCHDOG_S) -> None:
        self.hyprctl = hyprctl
        self.path = token_path(runtime_dir)
        self.seconds = seconds
        self.token: str | None = None

    @property
    def active(self) -> bool:
        return self.token is not None

    def ready(self) -> bool:
        """Hyprland knows the capture submap (and its way out, SUPER CTRL ALT Escape).

        Switching to a submap Hyprland has no binds for would still swallow every
        bind, with no key to leave it; before settings-hub.conf is sourced that
        is exactly the case, so the fallback is skipped then.
        """
        rc, out = self.hyprctl(["binds", "-j"])
        if rc != 0:
            return False
        try:
            items = json.loads(out)
        except ValueError:
            return False
        return any(isinstance(i, dict) and i.get("submap") == SUBMAP for i in items)

    def start(self) -> bool:
        """Enter the submap; False (and nothing done) if Hyprland does not have it."""
        if not self.ready():
            return False
        token = secrets.token_hex(16)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.{os.getpid()}")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as fh:
            fh.write(token + "\n")
        os.replace(tmp, self.path)
        self.token = token
        self.hyprctl(["dispatch", "submap", SUBMAP])
        self.hyprctl(["dispatch", "exec", watchdog_command(self.path, token, self.seconds)])
        return True

    def stop(self) -> None:
        if self.token is None:
            return
        try:
            if self.path.read_text().strip() == self.token:
                self.path.unlink()
        except OSError:
            pass
        self.token = None
        self.hyprctl(["dispatch", "submap", "reset"])


def reset_if_stuck(hyprctl: Runner) -> bool:
    """At startup: leave the capture submap if a crashed window left us in it.

    This also runs under a Lua config (Hyprland 0.57+), where the capture
    itself is off but settings-hub.lua still defines the submap: Lua takes only
    `hl.dsp.submap(...)`, a .conf only the plain form (it answers the Lua form
    with "Invalid dispatcher"), so try Lua first.
    """
    rc, out = hyprctl(["submap"])
    if rc == 0 and out.strip() == SUBMAP:
        _, reply = hyprctl(["dispatch", 'hl.dsp.submap("reset")'])
        if "Invalid dispatcher" in reply:  # a .conf Hyprland
            hyprctl(["dispatch", "submap", "reset"])
        return True
    return False
