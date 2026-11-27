"""Date, time and language of the system: time zone, network time, system
language, and the keyboard layouts of the login screen.

Read without root (`timedatectl show`, `localectl status`, `locale -a`). Each
change goes to systemd's own services through their command line tools:

    timedatectl set-timezone Europe/Oslo
    timedatectl set-ntp true
    localectl set-locale LANG=ru_RU.UTF-8 [the other LC_* as they were]
    localectl --no-convert set-x11-keymap us,ru pc105 "" grp:win_space_toggle

timedated and localed ask polkit, which asks for the password through the
agent on screen; the permission is for that one action, and it stays with the
short-lived command (never moved into this process: polkit would then keep it
for the whole window). Every value is checked against what the system offers
before a command is run.

The layouts of the session itself are Hyprland's input:kb_layout and
input:kb_options (variables backend); here only the helpers to show them.

No GTK.
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

BACKEND = WORKER = "timelang"
TIMEDATECTL = "/usr/bin/timedatectl"
LOCALECTL = "/usr/bin/localectl"
LOCALE = "/usr/bin/locale"
XKB_RULES = Path("/usr/share/X11/xkb/rules/base.lst")
ASK_TIMEOUT = 120  # the password dialog may stay open this long
KEYS = ("timezone", "ntp", "locale", "login-keys")
_TZ = re.compile(r"[A-Za-z][A-Za-z0-9_+\-]*(/[A-Za-z0-9_+\-]+)*")  # fullmatch
_LOCALE = re.compile(r"^[a-z]{2,3}(_[A-Z]{2})?\.UTF-8(@[a-z]+)?$")
PLAIN = ("C", "POSIX", "C.UTF-8", "C.utf8")  # always there, never in the list
_LAYOUT = re.compile(r"^[a-z]{2,8}(\([a-z0-9_]+\))?$")
_OPTION = re.compile(r"[a-z0-9_]+:[A-Za-z0-9_][A-Za-z0-9_.-]*")  # fullmatch
_LC = re.compile(r"^(LANG|LANGUAGE|LC_[A-Z_]+)=([A-Za-z0-9_.@:-]*)$")
LC_KEYS = frozenset({"LANG", "LANGUAGE", *(f"LC_{k}" for k in (
    "CTYPE", "NUMERIC", "TIME", "COLLATE", "MONETARY", "MESSAGES", "PAPER", "NAME",
    "ADDRESS", "TELEPHONE", "MEASUREMENT", "IDENTIFICATION"))})
_LABEL = re.compile(r"^[A-Za-z0-9 ]+$")  # "System Locale", "X11 Layout"; not "LANGUAGE=ru"


class NoAgent(PermissionError):
    """No polkit agent is running to ask for the password."""


class UnsafeLogin(ValueError):
    """The login screen would be left without a way to type a Latin password."""


# Layouts that type Latin letters (a single layout on the login screen must be
# one of these, or a Latin password cannot be typed there).
LATIN = frozenset({
    "us", "gb", "no", "se", "fi", "dk", "de", "at", "ch", "fr", "be", "nl", "es", "pt",
    "it", "pl", "cz", "sk", "hu", "ro", "hr", "si", "ee", "lv", "lt", "is", "ie", "tr",
    "br", "latam", "ca", "au", "nz", "za", "epo",
})


@dataclass(frozen=True)
class LoginKeys:
    """The keyboard of the login screen and console (localed's X11 keymap)."""

    layouts: str = ""  # "ru,us"
    model: str = ""
    variants: str = ""
    options: str = ""  # "terminate:ctrl_alt_bksp,grp:shifts_toggle"


@dataclass(frozen=True)
class Info:
    timezone: str = ""
    ntp: bool | None = None  # None: not known
    synced: bool | None = None
    can_ntp: bool = False
    timezones: tuple[str, ...] = ()
    locale: dict[str, str] = field(default_factory=dict)  # LANG=..., LC_TIME=...
    locales: tuple[str, ...] = ()  # "ru_RU.UTF-8", installed
    login: LoginKeys = LoginKeys()
    ok_time: bool = True  # timedatectl answered
    ok_locale: bool = True  # localectl answered


def parse_show(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        key, sep, value = line.partition("=")
        if sep:
            out[key.strip()] = value.strip()
    return out


def parse_localectl(text: str) -> tuple[dict[str, str], LoginKeys]:
    """`LC_ALL=C localectl status`: the locale lines (more than one: the first after
    "System Locale:", the rest indented below it) and the X11 keymap."""
    locale: dict[str, str] = {}
    x11: dict[str, str] = {}
    in_locale = False
    for raw in text.splitlines():
        label, sep, value = raw.partition(":")
        label = label.strip()
        if sep and not _LABEL.match(label):  # LANGUAGE=ru:en: a colon in a value
            label, sep, value = "", "", raw
        if sep and label == "System Locale":
            in_locale = True
            value = value.strip()
        elif sep and label in ("X11 Layout", "X11 Model", "X11 Variant", "X11 Options"):
            x11[label] = value.strip()
            in_locale = False
            continue
        elif sep and label:
            in_locale = False
            continue
        else:
            value = raw.strip()
        if in_locale:
            m = _LC.match(value)
            if m:
                locale[m.group(1)] = m.group(2)
    return locale, LoginKeys(x11.get("X11 Layout", ""), x11.get("X11 Model", ""),
                             x11.get("X11 Variant", ""), x11.get("X11 Options", ""))


def utf8_locales(text: str) -> tuple[str, ...]:
    """`locale -a` ("ru_RU.utf8") as the names localectl takes ("ru_RU.UTF-8")."""
    out = []
    for line in text.splitlines():
        name, dot, codeset = line.strip().partition(".")
        codeset, at, modifier = codeset.partition("@")  # ca_ES.utf8@valencia
        if dot and codeset.lower().replace("-", "") == "utf8" and name not in ("C", "POSIX"):
            full = f"{name}.UTF-8" + (f"@{modifier}" if at else "")
            if _LOCALE.match(full) and full not in out:
                out.append(full)
    return tuple(sorted(out))


def xkb_layouts(text: str) -> dict[str, str]:
    """base.lst's "! layout" section: code -> English name."""
    out: dict[str, str] = {}
    section = ""
    for line in text.splitlines():
        if line.startswith("!"):
            section = line[1:].strip()
            continue
        if section == "layout":
            code, _, name = line.strip().partition(" ")
            if code:
                out[code] = name.strip()
    return out


def login_safe(keys: LoginKeys) -> bool:
    """A Latin password can be typed: the first layout types Latin letters, or
    another one does and there is a key to switch to it."""
    layouts = split_list(keys.layouts)
    if not layouts or len(layouts) > 4:
        return False
    variants = str(keys.variants).split(",")

    def latin(i: int) -> bool:
        plain = i >= len(variants) or not variants[i].strip()
        return layouts[i].split("(")[0] in LATIN and "(" not in layouts[i] and plain

    if latin(0):
        return True
    return bool(switch_of(keys.options)) and any(latin(i) for i in range(1, len(layouts)))


def split_list(text: str) -> list[str]:
    return [p.strip() for p in str(text).split(",") if p.strip()]


def switch_of(options: str) -> str:
    """The grp:* option that switches layouts ("" for none)."""
    return next((o for o in split_list(options) if o.startswith("grp:")), "")


def with_switch(options: str, switch: str) -> str:
    """options with its grp:* switch replaced (others kept, in their order)."""
    kept = [o for o in split_list(options) if not o.startswith("grp:")]
    return ",".join(kept + ([switch] if switch else []))


@dataclass
class Backend:
    workers: object = None
    asks_password = True  # History runs undo off the GTK thread (window._execute)
    run: Callable[..., subprocess.CompletedProcess] = field(default=subprocess.run)
    xkb_rules: Path = XKB_RULES

    # ---- reading ----------------------------------------------------------------

    def _out(self, argv: list[str], timeout: float = 10) -> str | None:
        try:
            done = self.run(argv, capture_output=True, text=True, timeout=timeout, check=False,
                            env={**os.environ, "LC_ALL": "C"})
        except (OSError, subprocess.TimeoutExpired) as exc:
            log.warning("%s: %s", argv[0], exc)
            return None
        return done.stdout if done.returncode == 0 else None

    def probe(self) -> Info:
        shown = self._out([TIMEDATECTL, "show", "-p", "Timezone", "-p", "NTP",
                           "-p", "NTPSynchronized", "-p", "CanNTP"])
        values = parse_show(shown or "")
        zones = self._out([TIMEDATECTL, "list-timezones"]) or ""
        status = self._out([LOCALECTL, "status"])
        locale, login = parse_localectl(status or "")
        available = utf8_locales(self._out([LOCALE, "-a"]) or "")

        def yes(key: str) -> bool | None:
            return {"yes": True, "no": False}.get(values.get(key, ""))

        return Info(
            timezone=values.get("Timezone", ""), ntp=yes("NTP"), synced=yes("NTPSynchronized"),
            can_ntp=values.get("CanNTP") == "yes",
            timezones=tuple(z for z in (line.strip() for line in zones.splitlines())
                            if _TZ.fullmatch(z)),
            locale=locale, locales=available, login=login,
            ok_time=shown is not None, ok_locale=status is not None)

    def layouts(self) -> dict[str, str]:
        try:
            return xkb_layouts(self.xkb_rules.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            return {}

    # ---- changing (each asks for the password) -----------------------------------

    def _ask(self, argv: list[str]) -> None:
        try:
            done = self.run(argv, capture_output=True, text=True, timeout=ASK_TIMEOUT,
                            check=False, env={**os.environ, "LC_ALL": "C"})
        except subprocess.TimeoutExpired as exc:  # the password dialog left unanswered
            raise TimeoutError(str(exc)) from exc
        if done.returncode == 0:
            log.info("done: %s", " ".join(argv[1:3]))
            return
        said = (done.stderr or "").strip().splitlines()
        reason = said[-1] if said else f"exit {done.returncode}"
        low = reason.lower()
        if "interactive authentication" in low:
            raise NoAgent(reason)
        if "access denied" in low or "not authorized" in low or "authentication" in low:
            raise PermissionError(reason)
        raise RuntimeError(reason)

    def set_timezone(self, zone: str, info: Info | None = None) -> None:
        info = info or self.probe()
        if not _TZ.fullmatch(zone) or zone not in info.timezones:
            raise ValueError(f"unknown time zone {zone!r}")
        self._ask([TIMEDATECTL, "set-timezone", zone])

    def set_ntp(self, on: bool) -> None:
        self._ask([TIMEDATECTL, "set-ntp", "true" if on else "false"])

    def set_locale(self, values: dict[str, str], info: Info | None = None) -> None:
        """The whole locale (LANG and any LC_*): localectl replaces all of it."""
        info = info or self.probe()
        if not values.get("LANG"):
            raise ValueError("LANG is needed")
        for key, value in values.items():
            if key not in LC_KEYS or not re.fullmatch(r"[A-Za-z0-9_.@:-]+", value) \
                    or value.startswith("-"):
                raise ValueError(f"bad locale setting {key}={value!r}")
            if key == "LANGUAGE":  # a list of languages ("ru:en"), not a locale
                continue
            same = utf8_locales(value)
            if same and same[0] in info.locales:
                continue
            if value not in info.locales and value not in PLAIN \
                    and value != info.locale.get(key):
                raise ValueError(f"{value!r} is not installed")
        self._ask([LOCALECTL, "set-locale", *(f"{k}={v}" for k, v in values.items())])

    def set_login_keys(self, keys: LoginKeys) -> None:
        layouts = split_list(keys.layouts)
        if not layouts or len(layouts) > 4 or not all(_LAYOUT.match(x) for x in layouts):
            raise ValueError(f"bad layouts {keys.layouts!r}")
        options = split_list(keys.options)
        if not all(_OPTION.fullmatch(o) for o in options):
            raise ValueError(f"bad options {keys.options!r}")
        if not all(re.fullmatch(r"([A-Za-z0-9_][A-Za-z0-9_.-]*)?", v)
                   for v in keys.variants.split(",")):
            raise ValueError(f"bad variants {keys.variants!r}")
        if not re.fullmatch(r"([A-Za-z0-9_][A-Za-z0-9_.-]*)?", keys.model):
            raise ValueError(f"bad model {keys.model!r}")
        variants, model = keys.variants, keys.model
        if not login_safe(keys):
            raise UnsafeLogin(f"{keys.layouts!r}: no switch, or a single non-Latin layout")
        # --no-convert: the console keymap stays as it is
        self._ask([LOCALECTL, "--no-convert", "set-x11-keymap", ",".join(layouts),
                   model or "pc105", variants, ",".join(options)])

    # ---- History's Applier ---------------------------------------------------------

    def read(self, keys: list[str]) -> dict[str, Any]:
        info = self.probe()
        values = {"timezone": info.timezone, "ntp": info.ntp, "locale": dict(info.locale),
                  "login-keys": [info.login.layouts, info.login.model, info.login.variants,
                                 info.login.options]}
        return {k: values[k] for k in keys if k in values}

    def apply(self, values: dict[str, Any]) -> None:
        info = self.probe()
        for key in KEYS:  # one at a time; each may ask for the password
            if key not in values:
                continue
            value = values[key]
            if key == "timezone":
                self.set_timezone(str(value), info)
            elif key == "ntp" and isinstance(value, bool):
                self.set_ntp(value)
            elif key == "locale" and isinstance(value, dict):
                self.set_locale({str(k): str(v) for k, v in value.items()}, info)
            elif key == "login-keys" and isinstance(value, list) and len(value) == 4:
                self.set_login_keys(LoginKeys(*(str(v) for v in value)))


def register(history, backend: Backend) -> Backend:
    history.register(BACKEND, backend)
    return backend
