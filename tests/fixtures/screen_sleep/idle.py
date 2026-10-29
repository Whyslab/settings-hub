#!/usr/bin/env python3
"""
Простой, блокировка и сон: генерация ~/.config/hypr/hypridle.conf из конфига,
перезапуск hypridle, режим «не засыпать» и определение питания.

hypridle не умеет перечитывать конфиг и ничего не знает про батарею, поэтому:
  * тайминги живут в управляемой области файла между маркерами — всё остальное
    (шапка, блок general) остаётся ровно тем, что написал пользователь;
  * после записи процесс перезапускается: pkill + hyprctl dispatch exec
    (hypridle стартует из exec-once в hyprland.conf, а не через systemd —
     graphical-session.target в этой сессии неактивен);
  * набор таймингов выбирает демон по факту наличия зарядки.
"""

import os
import re
import signal
import subprocess
import time
from datetime import date
from pathlib import Path

from common import STEPS, atomic_write_text, state_path

HYPRIDLE_CONF = Path.home() / ".config" / "hypr" / "hypridle.conf"

MARK_START = "# >>> screen-sleep: этим блоком управляет окно «Экран и сон» (SUPER+SHIFT+N)"
MARK_END = "# <<< screen-sleep"

AC_ONLINE = Path("/sys/class/power_supply/AC/online")
CAFFEINE_PID_FILE = "caffeine.pid"
APPLIED_POWER_FILE = "applied_power"

# Команды намеренно те же, что стояли в конфиге раньше — меняются только
# тайминги и наличие самого шага.
STEP_SPECS = {
    "dim": {
        "var": "dim_timeout",
        "note": "приглушить подсветку экрана",
        "comment": "Приглушаем подсветку заранее, как мягкое предупреждение «скоро блокировка»",
        "on_timeout": "brightnessctl -s set 10%",
        "on_resume": "brightnessctl -r",
    },
    "lock": {
        "var": "lock_timeout",
        "note": "заблокировать экран (запускает hyprlock)",
        "comment": "Блокируем экран",
        "on_timeout": "loginctl lock-session",
        "on_resume": None,
    },
    "dpms": {
        "var": "dpms_timeout",
        "note": "выключить сигнал монитора (DPMS off)",
        "comment": "Гасим монитор, чтобы не жечь панель впустую",
        "on_timeout": "hyprctl dispatch dpms off",
        "on_resume": "hyprctl dispatch dpms on",
    },
    "suspend": {
        "var": "suspend_timeout",
        "note": "уйти в сон (systemctl suspend)",
        "comment": "Уходим в сон, если совсем никто не отреагировал",
        "on_timeout": "systemctl suspend",
        "on_resume": None,
    },
}

_VAR_NAMES = "|".join(spec["var"] for spec in STEP_SPECS.values())
_VAR_RE = re.compile(rf"^\$({_VAR_NAMES})\s*=\s*(\d+)")


def _env_c() -> dict:
    env = dict(os.environ)
    env["LC_ALL"] = "C"
    return env


# ---------------------------------------------------------------------------
# Разбор существующего конфига
# ---------------------------------------------------------------------------

def read_current_timeouts() -> dict:
    """Фактические тайминги из hypridle.conf, в минутах. {} если файла нет."""
    if not HYPRIDLE_CONF.exists():
        return {}
    var_to_step = {spec["var"]: step for step, spec in STEP_SPECS.items()}
    found = {}
    try:
        for line in HYPRIDLE_CONF.read_text().splitlines():
            match = _VAR_RE.match(line.strip())
            if match:
                step = var_to_step[match.group(1)]
                found[step] = max(1, round(int(match.group(2)) / 60))
    except OSError:
        return {}
    return found


def _strip_legacy(text: str) -> str:
    """Убрать старые $*_timeout, блоки listener и осиротевшие комментарии к ним."""
    lines = text.splitlines()
    out = []
    index = 0
    while index < len(lines):
        line = lines[index]
        stripped = line.strip()

        if _VAR_RE.match(stripped) or stripped.startswith("# ---- Интервалы"):
            index += 1
            continue

        # Нумерованный комментарий вида "# 3. Гасим монитор ..." всегда относился
        # к следующему listener — уходит вместе с ним
        if re.match(r"^#\s*\d+\.\s", stripped):
            index += 1
            continue

        if re.match(r"^listener\s*\{", stripped):
            depth = line.count("{") - line.count("}")
            index += 1
            while index < len(lines) and depth > 0:
                depth += lines[index].count("{") - lines[index].count("}")
                index += 1
            continue

        out.append(line)
        index += 1

    # схлопнуть пустоту, оставшуюся от вырезанных блоков
    collapsed = []
    for line in out:
        if not line.strip() and collapsed and not collapsed[-1].strip():
            continue
        collapsed.append(line)
    return "\n".join(collapsed).rstrip() + "\n"


def build_managed_block(profile: dict, power: str) -> str:
    """Управляемая область: переменные и listener'ы только для включённых шагов."""
    enabled = [step for step in STEPS if profile[step]["enabled"]]

    lines = [
        MARK_START,
        "# Правки внутри блока будут перезаписаны. Всё, что снаружи, сохраняется.",
        f"# Набор: {'от сети' if power == 'ac' else 'от батареи'}.",
        "",
    ]

    if not enabled:
        lines.append("# Все шаги выключены — hypridle ничего не делает.")
        lines.append(MARK_END)
        return "\n".join(lines) + "\n"

    width = max(len(STEP_SPECS[step]["var"]) for step in enabled)
    for step in enabled:
        spec = STEP_SPECS[step]
        minutes = profile[step]["minutes"]
        name = f"${spec['var']}".ljust(width + 1)
        lines.append(f"{name} = {minutes * 60:<6} # {minutes} мин — {spec['note']}")

    for step in enabled:
        spec = STEP_SPECS[step]
        lines.append("")
        lines.append(f"# {spec['comment']}")
        lines.append("listener {")
        lines.append(f"    timeout = ${spec['var']}")
        lines.append(f"    on-timeout = {spec['on_timeout']}")
        if spec["on_resume"]:
            lines.append(f"    on-resume = {spec['on_resume']}")
        lines.append("}")

    lines.append("")
    lines.append(MARK_END)
    return "\n".join(lines) + "\n"


def render(text: str, profile: dict, power: str) -> str:
    """Вставить/заменить управляемую область, не трогая остальной файл."""
    block = build_managed_block(profile, power)

    start = text.find(MARK_START)
    end = text.find(MARK_END)
    if start != -1 and end != -1 and end > start:
        tail = text[end + len(MARK_END):].lstrip("\n")
        head = text[:start].rstrip("\n")
        return (head + "\n\n" + block + ("\n" + tail if tail else "")).lstrip("\n")

    head = _strip_legacy(text)
    return head.rstrip("\n") + "\n\n" + block


# ---------------------------------------------------------------------------
# Применение
# ---------------------------------------------------------------------------

KEEP_BACKUPS = 7


def _prune_backups() -> None:
    """Оставить только KEEP_BACKUPS последних копий.

    Копия делается раз в сутки при каждой записи конфига и раньше никогда
    не убиралась — к 12.09.2026 в ~/.config/hypr накопилось 13 штук, и рост
    был бесконечным. Имена вида .bak-YYYY-MM-DD сортируются как даты.
    """
    olds = sorted(HYPRIDLE_CONF.parent.glob(f"{HYPRIDLE_CONF.name}.bak-*"))
    for stale in olds[:-KEEP_BACKUPS]:
        try:
            stale.unlink()
        except OSError:
            pass


def _backup_once() -> None:
    backup = HYPRIDLE_CONF.with_name(f"{HYPRIDLE_CONF.name}.bak-{date.today().isoformat()}")
    if not backup.exists() and HYPRIDLE_CONF.exists():
        backup.write_text(HYPRIDLE_CONF.read_text())
    _prune_backups()


def hypridle_running() -> bool:
    try:
        return subprocess.run(["/usr/bin/pgrep", "-x", "hypridle"],
                              capture_output=True, timeout=3).returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def restart_hypridle() -> tuple[bool, str]:
    """hypridle не перечитывает конфиг — только полный перезапуск."""
    try:
        subprocess.run(["/usr/bin/pkill", "-x", "hypridle"], capture_output=True, timeout=5)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass
    time.sleep(0.3)
    try:
        subprocess.run(["hyprctl", "dispatch", "exec", "hypridle"],
                       capture_output=True, text=True, timeout=5, env=_env_c())
    except FileNotFoundError:
        return False, "hyprctl не найден — это не сессия Hyprland?"
    except subprocess.TimeoutExpired:
        return False, "hyprctl не ответил вовремя"

    for _ in range(10):
        time.sleep(0.2)
        if hypridle_running():
            return True, ""
    return False, "hypridle не поднялся после перезапуска"


def apply_profile(cfg: dict, power: str) -> tuple[bool, str]:
    """Записать тайминги выбранного набора и перезапустить hypridle."""
    profile = cfg["idle"][power]
    try:
        previous = HYPRIDLE_CONF.read_text() if HYPRIDLE_CONF.exists() else ""
    except OSError as error:
        return False, f"не читается hypridle.conf: {error}"

    _backup_once()
    new_text = render(previous, profile, power)
    if new_text == previous and hypridle_running():
        _remember_power(power)
        return True, ""

    try:
        atomic_write_text(HYPRIDLE_CONF, new_text)
    except OSError as error:
        return False, f"не записывается hypridle.conf: {error}"

    ok, message = restart_hypridle()
    if not ok:
        # откатываемся на то, что заведомо работало
        try:
            atomic_write_text(HYPRIDLE_CONF, previous)
        except OSError:
            pass
        restart_hypridle()
        return False, f"{message} — конфиг возвращён к прежнему"

    _remember_power(power)
    return True, ""


# ---------------------------------------------------------------------------
# Питание
# ---------------------------------------------------------------------------

def on_ac() -> bool:
    try:
        return AC_ONLINE.read_text().strip() == "1"
    except OSError:
        pass
    # запасной путь: любой источник типа Mains
    try:
        for entry in Path("/sys/class/power_supply").iterdir():
            try:
                if (entry / "type").read_text().strip() == "Mains":
                    if (entry / "online").read_text().strip() == "1":
                        return True
            except OSError:
                continue
    except OSError:
        pass
    return False


def current_power() -> str:
    return "ac" if on_ac() else "battery"


def _remember_power(power: str) -> None:
    try:
        state_path(APPLIED_POWER_FILE).write_text(power + "\n")
    except OSError:
        pass


def applied_power() -> str | None:
    try:
        value = state_path(APPLIED_POWER_FILE).read_text().strip()
    except OSError:
        return None
    return value if value in ("ac", "battery") else None


# ---------------------------------------------------------------------------
# Режим «не засыпать»
# ---------------------------------------------------------------------------

def caffeine_pid() -> int | None:
    """PID живого держателя блокировки, иначе None (заодно чистит мусорный файл)."""
    path = state_path(CAFFEINE_PID_FILE)
    try:
        pid = int(path.read_text().strip())
    except (OSError, ValueError):
        return None
    try:
        cmdline = Path(f"/proc/{pid}/cmdline").read_bytes()
    except OSError:
        path.unlink(missing_ok=True)
        return None
    if b"systemd-inhibit" not in cmdline:
        path.unlink(missing_ok=True)
        return None
    return pid


def caffeine_active() -> bool:
    return caffeine_pid() is not None


def caffeine_set(enabled: bool) -> tuple[bool, str]:
    pid = caffeine_pid()

    if not enabled:
        if pid is not None:
            try:
                os.killpg(pid, signal.SIGTERM)
            except (ProcessLookupError, PermissionError):
                try:
                    os.kill(pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            state_path(CAFFEINE_PID_FILE).unlink(missing_ok=True)
        return True, ""

    if pid is not None:
        return True, ""

    try:
        process = subprocess.Popen(
            ["systemd-inhibit",
             "--what=idle:sleep",
             "--who=Экран и сон",
             "--why=Режим «не засыпать»",
             "--mode=block",
             "sleep", "infinity"],
            start_new_session=True,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError:
        return False, "systemd-inhibit не найден"

    time.sleep(0.3)
    if process.poll() is not None:
        return False, "не удалось включить режим «не засыпать»"

    state_path(CAFFEINE_PID_FILE).write_text(f"{process.pid}\n")
    return True, ""
