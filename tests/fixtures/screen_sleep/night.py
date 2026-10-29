#!/usr/bin/env python3
"""
Ночной фильтр: расчёт нужной цветовой температуры и её применение
через hyprsunset (hyprctl). Перенесено из nightfilter_common.py.
"""

import subprocess

from common import (
    MAX_TEMP, RAMP_STEP, RAMP_INTERVAL_MIN, RAMP_BOTH_DIRECTIONS, SERVICE_NAME,
)

HYPRCTL = "hyprctl"

# Утилиты печатают числа по локали; для разбора вывода нужна предсказуемая
ENV_C = {"LC_ALL": "C"}


def _run(cmd: list, timeout: int = 2) -> subprocess.CompletedProcess:
    import os
    env = dict(os.environ)
    env.update(ENV_C)
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env)


def apply_temperature(kelvin) -> tuple[bool, str]:
    """Немедленно применить температуру через hyprctl. Возвращает (успех, сообщение)."""
    try:
        result = _run([HYPRCTL, "hyprsunset", "temperature", str(int(kelvin))])
        if result.returncode != 0:
            return False, "hyprsunset не отвечает (демон hyprsunset запущен?)"
        return True, ""
    except FileNotFoundError:
        return False, "hyprctl не найден — это не сессия Hyprland?"
    except subprocess.TimeoutExpired:
        return False, "hyprctl не ответил вовремя"


def read_temperature() -> int | None:
    """Какая температура сейчас на экране. None, если hyprsunset не отвечает."""
    try:
        result = _run([HYPRCTL, "hyprsunset", "temperature"])
        if result.returncode != 0:
            return None
        return int(result.stdout.strip())
    except (FileNotFoundError, subprocess.TimeoutExpired, ValueError):
        return None


def check_hyprsunset_alive() -> tuple[bool, str]:
    try:
        result = _run([HYPRCTL, "hyprsunset", "profile"])
        if result.returncode != 0:
            return False, "hyprsunset не запущен. Добавь в hyprland.conf: exec-once = hyprsunset"
        return True, ""
    except FileNotFoundError:
        return False, "hyprctl не найден — это не сессия Hyprland?"
    except subprocess.TimeoutExpired:
        return False, "hyprctl не ответил вовремя"


def check_daemon_alive() -> tuple[bool, str]:
    try:
        result = _run(["systemctl", "--user", "is-active", SERVICE_NAME])
        if result.stdout.strip() != "active":
            return False, ("Демон screen-sleep-daemon не запущен — расписание и "
                           "переключение сеть/батарея работать не будут")
        return True, ""
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False, "Не удалось проверить статус демона"


# ---------------------------------------------------------------------------
# Логика плавного перехода
# ---------------------------------------------------------------------------

def ramp_duration_minutes(target_temp: int) -> float:
    """Сколько минут займёт переход от MAX_TEMP до target_temp с шагом RAMP_STEP."""
    if target_temp >= MAX_TEMP:
        return 0.0
    steps_needed = (MAX_TEMP - target_temp) / RAMP_STEP
    return steps_needed * RAMP_INTERVAL_MIN


def compute_target_temperature(now_minutes: float, night: dict) -> int:
    """
    Какая температура должна быть ПРЯМО СЕЙЧАС, исходя из текущего времени
    (now_minutes — минуты с полуночи, может быть дробным) и расписания.
    Корректно обрабатывает окно, пересекающее полночь (напр. on=22:00, off=07:00).
    """
    on_t = night["on_hour"] * 60 + night["on_minute"]
    off_t = night["off_hour"] * 60 + night["off_minute"]
    ramp_min = ramp_duration_minutes(night["target_temp"])

    # "сколько минут назад был последний раз пройден этот рубеж" (по модулю суток)
    since_on = (now_minutes - on_t) % 1440
    since_off = (now_minutes - off_t) % 1440

    if since_on < ramp_min:
        # плавно снижаем от MAX_TEMP к target_temp
        steps = int(since_on // RAMP_INTERVAL_MIN)
        return int(max(MAX_TEMP - steps * RAMP_STEP, night["target_temp"]))

    if RAMP_BOTH_DIRECTIONS and since_off < ramp_min:
        steps = int(since_off // RAMP_INTERVAL_MIN)
        return int(min(night["target_temp"] + steps * RAMP_STEP, MAX_TEMP))

    if since_on < since_off:
        # рубеж "включения" пройден позже, чем рубеж "выключения" — значит мы в ночи
        return int(night["target_temp"])

    return int(MAX_TEMP)
