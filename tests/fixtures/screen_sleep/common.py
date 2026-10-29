#!/usr/bin/env python3
"""
Общее для «Экрана и сна»: пути, структура конфига, атомарная запись.

Один конфиг на два раздела:
  night — ночной фильтр (цветовая температура и расписание)
  idle  — простой: приглушение / блокировка / гашение монитора / сон,
          двумя наборами — от сети (ac) и от батареи (battery)

Держать всё в одном месте, чтобы GUI и демон не разъезжались.
"""

import json
import os
import tempfile
from pathlib import Path

APP_NAME = "screen-sleep"
SERVICE_NAME = f"{APP_NAME}-daemon.service"

CONFIG_DIR = Path.home() / ".config" / APP_NAME
CONFIG_FILE = CONFIG_DIR / "config.json"
STATE_DIR = Path.home() / ".local" / "state" / APP_NAME

# Откуда переносим настройки при первом запуске (старое приложение nightfilter)
LEGACY_CONFIG_FILE = Path.home() / ".config" / "nightfilter" / "config.json"

# ---- ночной фильтр ----
MIN_TEMP = 2000          # максимально тёплый (крайнее положение слайдера)
MAX_TEMP = 6500          # нейтрально / день / выключено
NIGHT_MARK_TEMP = 2700   # метка "оптимум для сна" на слайдере (не жёсткое значение)

RAMP_STEP = 500              # K за один шаг плавного перехода
RAMP_INTERVAL_MIN = 15       # минут между шагами
RAMP_BOTH_DIRECTIONS = False # утром — мгновенно, без плавного шага

CHECK_INTERVAL_SECONDS = 15  # как часто демон сверяется с расписанием и питанием

DEFAULT_ON_HOUR, DEFAULT_ON_MINUTE = 22, 0
DEFAULT_OFF_HOUR, DEFAULT_OFF_MINUTE = 7, 0

# ---- простой ----
STEPS = ("dim", "lock", "dpms", "suspend")

STEP_LABELS = {
    "dim": "Приглушить экран",
    "lock": "Заблокировать",
    "dpms": "Погасить монитор",
    "suspend": "Уйти в сон",
}

PROFILES = ("ac", "battery")

PROFILE_LABELS = {
    "ac": "От сети",
    "battery": "От батареи",
}

MIN_MINUTES, MAX_MINUTES = 1, 600

# Пресеты применяются к открытому набору; None = шаг выключен
PRESETS = {
    "Обычный":   {"dim": 60, "lock": 70, "dpms": 80, "suspend": 120},
    "Кино":      {"dim": None, "lock": None, "dpms": None, "suspend": None},
    "Экономный": {"dim": 5, "lock": 7, "dpms": 8, "suspend": 15},
}

DEFAULT_NIGHT = {
    "target_temp": NIGHT_MARK_TEMP,
    "on_hour": DEFAULT_ON_HOUR,
    "on_minute": DEFAULT_ON_MINUTE,
    "off_hour": DEFAULT_OFF_HOUR,
    "off_minute": DEFAULT_OFF_MINUTE,
    "manual_override": False,
}

DEFAULT_IDLE_AC = {"dim": 60, "lock": 70, "dpms": 80, "suspend": 120}
DEFAULT_IDLE_BATTERY = {"dim": 5, "lock": 7, "dpms": 8, "suspend": 20}


def _steps_from_minutes(minutes_map: dict) -> dict:
    """{"dim": 60, ...} -> {"dim": {"enabled": True, "minutes": 60}, ...}"""
    result = {}
    for step in STEPS:
        value = minutes_map.get(step)
        if value is None:
            result[step] = {"enabled": False, "minutes": DEFAULT_IDLE_AC[step]}
        else:
            result[step] = {"enabled": True, "minutes": int(value)}
    return result


def default_config() -> dict:
    return {
        "night": dict(DEFAULT_NIGHT),
        "idle": {
            "ac": _steps_from_minutes(DEFAULT_IDLE_AC),
            "battery": _steps_from_minutes(DEFAULT_IDLE_BATTERY),
        },
    }


# ---------------------------------------------------------------------------
# Чтение / запись
# ---------------------------------------------------------------------------

def atomic_write_text(path: Path, text: str) -> None:
    """Записать так, чтобы читатель никогда не увидел половину файла."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


def _sanitize_night(raw: dict) -> dict:
    night = dict(DEFAULT_NIGHT)
    if not isinstance(raw, dict):
        return night
    try:
        night["target_temp"] = max(MIN_TEMP, min(MAX_TEMP, int(raw.get("target_temp", NIGHT_MARK_TEMP))))
        night["on_hour"] = int(raw.get("on_hour", DEFAULT_ON_HOUR)) % 24
        night["on_minute"] = int(raw.get("on_minute", DEFAULT_ON_MINUTE)) % 60
        night["off_hour"] = int(raw.get("off_hour", DEFAULT_OFF_HOUR)) % 24
        night["off_minute"] = int(raw.get("off_minute", DEFAULT_OFF_MINUTE)) % 60
        night["manual_override"] = bool(raw.get("manual_override", False))
    except (ValueError, TypeError):
        return dict(DEFAULT_NIGHT)
    return night


def _sanitize_profile(raw: dict, fallback: dict) -> dict:
    profile = _steps_from_minutes(fallback)
    if not isinstance(raw, dict):
        return profile
    for step in STEPS:
        entry = raw.get(step)
        if not isinstance(entry, dict):
            continue
        try:
            minutes = int(entry.get("minutes", fallback[step]))
        except (ValueError, TypeError):
            minutes = fallback[step]
        profile[step] = {
            "enabled": bool(entry.get("enabled", True)),
            "minutes": max(MIN_MINUTES, min(MAX_MINUTES, minutes)),
        }
    return profile


def _migrate() -> dict:
    """Первый запуск: собрать конфиг из старого nightfilter и живого hypridle.conf."""
    cfg = default_config()

    if LEGACY_CONFIG_FILE.exists():
        try:
            cfg["night"] = _sanitize_night(json.loads(LEGACY_CONFIG_FILE.read_text()))
        except (json.JSONDecodeError, OSError):
            pass

    # Тайминги простоя от сети берём фактические — чтобы установка ничего не поменяла
    from idle import read_current_timeouts  # локальный импорт: idle тянет common
    current = read_current_timeouts()
    if current:
        merged = dict(DEFAULT_IDLE_AC)
        merged.update(current)
        cfg["idle"]["ac"] = _steps_from_minutes(merged)

    return cfg


def load_config() -> dict:
    if not CONFIG_FILE.exists():
        cfg = _migrate()
        save_config(cfg)
        return cfg

    try:
        raw = json.loads(CONFIG_FILE.read_text())
    except (json.JSONDecodeError, OSError, ValueError):
        return default_config()

    if not isinstance(raw, dict):
        return default_config()

    raw_idle = raw.get("idle") if isinstance(raw.get("idle"), dict) else {}
    return {
        "night": _sanitize_night(raw.get("night", {})),
        "idle": {
            "ac": _sanitize_profile(raw_idle.get("ac", {}), DEFAULT_IDLE_AC),
            "battery": _sanitize_profile(raw_idle.get("battery", {}), DEFAULT_IDLE_BATTERY),
        },
    }


def save_config(cfg: dict) -> None:
    atomic_write_text(CONFIG_FILE, json.dumps(cfg, indent=2, ensure_ascii=False) + "\n")


def state_path(name: str) -> Path:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    return STATE_DIR / name
