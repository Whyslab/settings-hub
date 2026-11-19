"""Анимация сворачивания: какие бывают и что выбрано. Без GTK.

Выбор лежит в ~/.config/minimize/animation.json:
    {"style": "fly", "speed": "normal"}
Пишут его «Настройки» (страница «Анимации»), читают core.py и fx.py при
каждом сворачивании — перезапуск не нужен. Нет файла или он испорчен —
действует DEFAULT.

Анимацию рисует fx.py по снимку окна; само окно Hyprland убирает мгновенно.
Возврат окна — то же движение в обратную сторону.
"""

import json
import os
import tempfile

CONFIG_DIR = os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"),
                          "minimize")
CONFIG = os.path.join(CONFIG_DIR, "animation.json")

# id → (название, описание, длительность при обычной скорости, с)
STYLES = {
    "fly":      ("В кнопку на панели", "Окно уменьшается и улетает в кнопку свёрнутых окон.", 0.42),
    "fade":     ("Угасание", "Окно тает на месте.", 0.25),
    "shrink":   ("Уменьшение", "Окно сжимается к середине и тает.", 0.28),
    "slide":    ("Вниз", "Окно уезжает вниз и тает.", 0.32),
    "dissolve": ("Рассыпается на пиксели", "Окно рассыпается в пыль, как при закрытии.", 0.85),
    "none":     ("Без анимации", "Окно исчезает сразу.", 0.0),
}
ORDER = ("fly", "fade", "shrink", "slide", "dissolve", "none")
SPEEDS = {"fast": 0.6, "normal": 1.0, "slow": 1.6}
SPEED_ORDER = ("fast", "normal", "slow")
SPEED_TITLES = {"fast": "Быстро", "normal": "Обычно", "slow": "Медленно"}
DEFAULT = {"style": "fly", "speed": "normal"}


def load(path: str = CONFIG) -> dict:
    """Выбор с подстановкой значений по умолчанию; чужие значения отбрасываются."""
    out = dict(DEFAULT)
    try:
        with open(path) as f:
            data = json.load(f)
    except (OSError, ValueError):
        return out
    if isinstance(data, dict):
        if data.get("style") in STYLES:
            out["style"] = data["style"]
        if data.get("speed") in SPEEDS:
            out["speed"] = data["speed"]
    return out


def save(choice: dict, path: str = CONFIG) -> dict:
    """Записать выбор целиком (атомарно). Неизвестное значение — ValueError."""
    style, speed = choice.get("style"), choice.get("speed")
    if style not in STYLES:
        raise ValueError(f"неизвестная анимация: {style!r}")
    if speed not in SPEEDS:
        raise ValueError(f"неизвестная скорость: {speed!r}")
    data = {"style": style, "speed": speed}
    folder = os.path.dirname(path)
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, prefix=".animation.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(data, f, ensure_ascii=False)
            f.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise
    return data


def duration(choice: dict) -> float:
    """Сколько секунд длится анимация выбранного вида и скорости."""
    return STYLES[choice["style"]][2] * SPEEDS[choice["speed"]]
