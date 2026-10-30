"""Every piece of user-facing text, in Russian.

This is the only module (besides README.ru.md and test fixtures) that may
contain Cyrillic; CI enforces that. Code elsewhere refers to the names below.
Search keywords live here too, so a translator sees them next to the titles.
"""

APP_TITLE = "Настройки"

# Search: the same physical keys on the US and the Russian layout, so a query
# typed with the wrong layout can be converted. Unshifted, then shifted keys.
LAYOUT_EN = "`qwertyuiop[]asdfghjkl;'zxcvbnm,."
LAYOUT_RU = "ёйцукенгшщзхъфывапролджэячсмитьбю"
LAYOUT_EN_SHIFTED = '~{}:"<>'
LAYOUT_RU_SHIFTED = "ёхъжэбю"
# "ё" is searched as "е".
YO, YE = "ё", "е"
APP_COMMENT = "Настройки рабочего стола в одном окне"
APP_KEYWORDS = "настройки;параметры;settings;"

SEARCH_PLACEHOLDER = "Поиск"
SEARCH_NOTHING = "Ничего не найдено"

# Sidebar group titles, by registry group id.
GROUPS = {
    "display": "Экран и вид",
    "keyboard": "Клавиатура и окна",
    "system": "Система",
}

# Page titles, search keywords and searchable rows, by page id.
# rows: row id -> (label, extra keywords). A row id is what the page uses to
# scroll to and highlight the row when a search result is opened.
PAGES = {
    "screen-sleep": {
        "title": "Экран и сон",
        "keywords": [
            "сон", "блокировка", "простой", "ночной", "фильтр", "тёплый",
            "батарея", "не засыпать", "расписание", "экран", "яркость",
        ],
        "rows": {
            "now": ("Сейчас", ["статус", "питание", "hypridle", "hyprsunset", "демон"]),
            "caffeine": ("Не засыпать", ["не засыпать", "не гасить", "кофеин", "бодрствовать"]),
            "ac": ("От сети", [
                "сон", "простой", "блокировка", "приглушить", "погасить", "зарядка",
                "пресет", "набор", "кино", "экономный", "обычный",
            ]),
            "battery": ("От батареи", [
                "сон", "простой", "блокировка", "приглушить", "погасить", "батарея",
                "пресет", "набор", "кино", "экономный", "обычный",
            ]),
            "night": ("Ночной фильтр", ["ночной", "фильтр", "тёплый", "температура", "ползунок"]),
            "schedule": ("По расписанию", ["расписание", "ручной", "автоматически"]),
            "target": ("Цель ночью", ["цель", "ночь", "кельвин"]),
            "times": ("Начало разогрева и выключение", ["время", "разогрев", "утро", "вечер"]),
            "off-now": ("Выключить фильтр сейчас", ["выключить", "дневной"]),
        },
    },
    "wallpaper": {
        "title": "Обои и тема",
        "keywords": [
            "обои", "фон", "картинка", "тема", "цвета", "яркий",
            "приглушённый", "sddm", "блокировка",
        ],
        "rows": {
            "target": ("Куда ставить", [
                "рабочий стол", "экран блокировки", "экран входа", "все три", "цель",
            ]),
            "grid": ("Картинки", ["картинка", "фон", "миниатюры", "выбрать обои"]),
            "rofi": ("Открыть сетку rofi", ["rofi", "сетка", "пикер"]),
            "random": ("Случайные обои", ["случайные", "случайно", "перемешать", "каждый вход"]),
            "theme": ("Интерфейс под обои", [
                "тема", "цвета", "яркий", "приглушённый", "оттенок", "wallpaper-theme",
                "панель", "перекрасить",
            ]),
        },
    },
    "animations": {
        "title": "Анимации",
        "keywords": ["анимация", "пресет", "распад", "скорость", "движение", "эффекты"],
        "rows": {
            "presets": ("Готовые наборы", ["набор", "пресет", "распад", "превью"]),
            "open": ("Открытие окон", ["открытие", "появление", "окно"]),
            "close": ("Закрытие окон", ["закрытие", "исчезновение", "распад", "окно"]),
            "workspaces": ("Переключение столов", ["стол", "рабочий стол", "переключение"]),
            "layers": ("Меню и уведомления", ["меню", "уведомления", "панель"]),
        },
    },
    "binds": {
        "title": "Бинды",
        "keywords": ["бинд", "клавиша", "сочетание", "горячая", "клавиатура", "ярлык"],
        "rows": {
            "list": ("Все бинды", [
                "переназначить", "отключить", "вернуть", "сочетание клавиш", "hyprland",
            ]),
            "add": ("Добавить бинд", ["добавить", "новое сочетание", "команда"]),
        },
    },
    "history": {
        "title": "История",
        "keywords": ["история", "отмена", "откат", "журнал", "изменения"],
        "rows": {
            "undo": ("Отменить последнее изменение", ["отменить", "назад", "ctrl+z"]),
            "log": ("Журнал изменений", ["список", "правки"]),
        },
    },
}

# History page.
HISTORY_UNDO_GROUP = "Отменить"
HISTORY_UNDO_ROW = PAGES["history"]["rows"]["undo"][0]
HISTORY_UNDO_BUTTON = "Отменить"
HISTORY_UNDO_HINT = "Ctrl+Z в любом месте окна"
HISTORY_LOG_GROUP = "Изменения"
HISTORY_EMPTY = "Изменений пока нет"
HISTORY_UNDO_PREFIX = "Отмена"
HISTORY_UNDONE = "Отменено: {label}"
HISTORY_NOTHING_TO_UNDO = "Нечего отменять"
HISTORY_NO_APPLIER = "Не умею применять: {backends}"
HISTORY_APPLY_FAILED = "Не удалось вернуть: {error}"
HISTORY_CONFLICT_TITLE = "Значения менялись вне окна"
HISTORY_CONFLICT_BODY = (
    "После этих правок значения поменял кто-то другой:\n{groups}\n\n"
    "Вернуть всё равно или пропустить эти правки?"
)
HISTORY_CONFLICT_REVERT_ALL = "Вернуть всё"
HISTORY_CONFLICT_SKIP = "Пропустить их"
HISTORY_CONFLICT_CANCEL = "Отмена"
HISTORY_MORE = "и ещё {n}"

# Human names of the backends, shown next to a history entry.
BACKENDS = {
    "screen-sleep": "Экран и сон",
    "night": "Ночной фильтр",
    "caffeine": "Не засыпать",
    "wallpaper": "Обои",
    "theme": "Тема",
    "animations": "Анимации",
    "binds": "Бинды",
}

# settings-open shows this when the window could not be started at all.
OPEN_FAILED = "Настройки не запустились, см. {log}"

# ---- Screen and sleep page -------------------------------------------------

SS_ROWS = PAGES["screen-sleep"]["rows"]
SS_NOW_GROUP = "Сейчас"
SS_POWER = "Питание"
SS_POWER_NAMES = {"ac": "от сети", "battery": "от батареи"}
SS_POWER_ACTIVE = "Действует набор «{profile}»"
SS_CHECK_HYPRSUNSET = "Ночной фильтр (hyprsunset)"
SS_CHECK_HYPRIDLE = "Простой и блокировка (hypridle)"
SS_CHECK_DAEMON = "Расписание и питание (демон)"
SS_RUNNING = "Работает"
SS_STOPPED = "Не запущен"
SS_UNKNOWN = "Проверяю…"
SS_HYPRIDLE_DOWN = "Простой и блокировка не работают"

SS_CAFFEINE = SS_ROWS["caffeine"][0]
SS_CAFFEINE_ON = "Экран не гаснет, не блокируется и компьютер не засыпает"
SS_CAFFEINE_OFF = "Простой идёт по наборам ниже"

# Profile and step names, by the ids screen-sleep uses in config.json.
SS_PROFILES = {"ac": "От сети", "battery": "От батареи"}
SS_PROFILE_NOW = "{profile} · сейчас"
SS_STEPS = {
    "dim": "Приглушить экран",
    "lock": "Заблокировать",
    "dpms": "Погасить монитор",
    "suspend": "Уйти в сон",
}
SS_MINUTES = "мин"
SS_AFTER = "через"
SS_PRESETS_ROW = "Готовые наборы"
# Preset ids -> the names screen-sleep's common.PRESETS uses as keys.
SS_PRESETS = {"normal": "Обычный", "movie": "Кино", "eco": "Экономный"}
SS_PRESET_LABEL = "Набор «{preset}» → {profile}"
SS_ORDER_WARNING = "Шаги идут не по возрастанию времени: позднее время у более раннего шага"
SS_PROFILE_NOTE = "Простой считается с последнего касания клавиатуры или мыши."

SS_NIGHT_GROUP = "Ночной фильтр"
SS_NIGHT_NOW = "Сейчас на экране"
SS_KELVIN = "{value} K"
SS_KELVIN_UNKNOWN = "— K"
SS_MARK_SLEEP = "для сна"
SS_MARK_OFF = "выкл"
SS_SCHEDULE = SS_ROWS["schedule"][0]
SS_SCHEDULE_ON = "Температуру меняет расписание"
SS_SCHEDULE_OFF = "Ручной режим: до следующей границы расписания держится ползунок"
SS_TARGET = SS_ROWS["target"][0]
SS_TARGET_HINT = "Самая тёплая температура ночью"
SS_ON_TIME = "Начало разогрева"
SS_ON_TIME_HINT = "Плавно, по {step} K каждые {minutes} мин"
SS_OFF_TIME = "Выключение"
SS_OFF_TIME_HINT = "Утром сразу, без плавного перехода"
SS_OFF_NOW = "Выключить сейчас"
SS_OFF_NOW_HINT = "Нейтральный цвет до следующей границы расписания"
SS_NIGHT_NOTE = "Вправо — теплее. Движение ползунка включает ручной режим."

# History labels, by config path (and the two keys that are not in config.json).
SS_LABEL_STEP = "{profile}: {step}"
SS_LABEL_TARGET = "Ночной фильтр: цель ночью"
SS_LABEL_ON = "Ночной фильтр: начало разогрева"
SS_LABEL_OFF = "Ночной фильтр: выключение"
SS_LABEL_SCHEDULE = "Ночной фильтр: по расписанию"
SS_LABEL_SLIDER = "Ночной фильтр: температура сейчас"
SS_LABEL_CAFFEINE = "Не засыпать"

SS_APPLYING = "Применяю…"
SS_SAVED = "Сохранено"
SS_APPLIED = "Применено: действует набор «{profile}»"
SS_APPLIED_LATER = "Сохранено: этот набор включится при смене питания"
SS_APPLY_FAILED = "Не удалось применить: {error}"
SS_WRITE_FAILED = "Не удалось сохранить: {error}"
SS_TEMP_FAILED = "Ночной фильтр: {error}"
SS_CAFFEINE_FAILED = "«Не засыпать»: {error}"

SS_SETUP_GROUP = "Экран и сон"
SS_SETUP_MISSING = "Экран и сон не настроен — откройте старое окно один раз"
SS_SETUP_MISSING_HINT = "Оно создаст файл настроек; потом всё настраивается здесь."
SS_SETUP_ERROR = "Не удалось загрузить модули «Экран и сон»"
SS_OPEN_OLD = "Открыть старое окно"

# ---- Wallpaper and theme page ----------------------------------------------

WP_ROWS = PAGES["wallpaper"]["rows"]
# Target ids are wallpaper.sh's: desktop, lock, sddm, all.
WP_TARGETS = {
    "desktop": "Рабочий стол",
    "lock": "Блокировка",
    "sddm": "Экран входа",
    "all": "Все три",
}
WP_TARGET_NAMES = {
    "desktop": "рабочий стол",
    "lock": "экран блокировки",
    "sddm": "экран входа",
    "all": "все три фона",
}
WP_TARGET_ROW = WP_ROWS["target"][0]
WP_NOW = "Сейчас: {name}"
WP_NOW_RANDOM = "Сейчас: случайные обои"
WP_NOW_MIXED = "Сейчас на целях разные картинки"
WP_NONE = "не задано"
WP_GRID_ROW = WP_ROWS["grid"][0]
WP_GRID_HINT = "Нажмите на картинку, чтобы поставить её. Синяя рамка — то, что стоит сейчас."
WP_EMPTY = "В папке {folder} нет картинок"
WP_RANDOM_WARNING = "Выбор картинки выключит случайные обои на этой цели"
WP_ROFI = WP_ROWS["rofi"][0]
WP_ROFI_HINT = "Прежний выбор обоев: сетка во весь экран"
WP_ROFI_BUTTON = "Открыть"
WP_RANDOM_GROUP = WP_ROWS["random"][0]
WP_RANDOM_TARGETS = {
    "desktop": "Рабочий стол",
    "lock": "Экран блокировки",
    "sddm": "Экран входа",
}
WP_RANDOM_NOTE = ("Новая картинка при каждом входе в систему, у блокировки — при каждой "
                  "блокировке. Включение сразу ставит случайную картинку.")
WP_THEME_GROUP = WP_ROWS["theme"][0]
WP_THEME_ROW = "Цвета интерфейса"
# Mode ids are wallpaper-theme's: off, vivid, tinted.
WP_THEME_MODES = {"off": "Выключен", "vivid": "Яркий", "tinted": "Приглушённый"}
WP_THEME_HINTS = {
    "off": "Обычная тема Monochrome Vivid",
    "vivid": "Цвета берутся из обоев",
    "tinted": "Чёрно-белое с оттенком обоев",
}
WP_THEME_UNKNOWN = "Не удалось узнать режим"
WP_THEME_MISSING = "wallpaper-theme не установлен"
WP_THEME_NOTE = ("Панель перекрасится за несколько секунд, rofi — при следующем открытии, "
                 "программы на GTK — после перезапуска.")
WP_SETUP_GROUP = "Обои"
WP_SETUP_MISSING = "Не найден скрипт обоев"
WP_SETUP_MISSING_HINT = "Ожидается {path}"

WP_LABEL_SET = "Обои: {target}"
WP_LABEL_RANDOM = "Случайные обои: {target}"
WP_LABEL_THEME = "Интерфейс под обои"
WP_APPLYING = "Ставлю обои…"
WP_SET_DONE = "{target}: {name}"
WP_RANDOM_ON = "Случайные обои включены: {target}"
WP_RANDOM_OFF = "Случайные обои выключены: {target}"
WP_THEME_APPLYING = "Перекрашиваю интерфейс…"
WP_THEME_DONE = "Интерфейс под обои: {mode}"
WP_FAILED = "Не удалось: {error}"
WP_THUMBS = "Готовлю миниатюры: {n}"

# ---- Animations page -------------------------------------------------------
# Category, variant, speed and preset names come from rofi-launcher's own
# Russian strings (the animations module, with its language set to Russian).

AN_ROWS = PAGES["animations"]["rows"]
AN_PRESETS_GROUP = AN_ROWS["presets"][0]
AN_PRESET_ROW = "Набор"
AN_PRESET_NOW = "Сейчас: {name}"
AN_PRESET_NONE = "Набор не выбран"
AN_PRESETS_NOTE = ("Набор меняет всё сразу и сбрасывает донастройку ниже. "
                   "«Посмотреть» на несколько секунд прячет окно и показывает анимацию вживую, "
                   "ничего не сохраняя.")
AN_VARIANT_ROW = "Вариант"
AN_SPEED_ROW = "Скорость"
AN_PREVIEW = "Посмотреть"
AN_PREVIEW_HINT = "Показать вживую: окно спрячется на несколько секунд"
AN_SETUP_GROUP = "Анимации"
AN_SETUP_ERROR = "Не удалось загрузить модуль анимаций rofi-launcher"

AN_LABEL_PRESET = "Анимации: набор"
AN_LABEL_PRESET_NAMED = "Анимации: набор «{name}»"
AN_LABEL_OVERRIDE = "Анимации: {category}"
AN_LABEL_SPEED = "Анимации: {category}, скорость"
AN_APPLYING = "Применяю…"
AN_PREVIEWING = "Показываю…"
AN_PREVIEW_FAILED = "Не удалось показать: {error}"
AN_FAILED = "Не удалось применить: {error}"

# ---- Binds page --------------------------------------------------------------

BN_ROWS = PAGES["binds"]["rows"]
BN_SEARCH = "Найти бинд"
BN_NOTHING = "Ничего не найдено"
BN_LUA = "Hyprland читает Lua-конфиг — бинды пока только для просмотра"
BN_LUA_HINT = "Редактор биндов под Lua появится позже. Сейчас бинды задаются в {path}."
BN_LUA_FUNCTION = "Lua-функция"
BN_NOT_SOURCED = "settings-hub.conf пока не подключён к hyprland.conf"
BN_NOT_SOURCED_HINT = "Правки сохранятся, но подействуют после установки."
BN_READ_FAILED = "Не удалось прочитать бинды"
BN_LIVE_UNKNOWN = "Живой список Hyprland недоступен: сверка не проведена."
BN_MISMATCH = "В живом Hyprland этот бинд выглядит иначе, чем в файле"
BN_SETUP_GROUP = "Бинды"
BN_NOTE = ("Правки пишутся только в свой блок settings-hub.conf; hyprland.conf не меняется. "
           "«Вернуть как было» убирает правку этого сочетания.")
BN_MENU = "Действия"
BN_REBIND = "Переназначить…"
BN_DISABLE = "Отключить"
BN_DISABLE_ONE = "Отключить: {name}"
BN_DISABLE_ALL = "Отключить всё"
BN_REVERT = "Вернуть как было"
BN_PRESS = "Нажмите сочетание…"
BN_PRESS_HINT = "Esc — отмена"
BN_MOVED_FROM = "было: {combo}"
BN_DISABLED_NOTE = "отключено"
BN_READ_ONLY = "Только для чтения: бинд режима не правится здесь"
BN_ADD_GROUP = BN_ROWS["add"][0]
BN_ADD_COMMAND = "Команда"
BN_ADD_COMMAND_HINT = "Например, kitty или ~/bin/script.sh"
BN_ADD_COMBO = "Сочетание"
BN_ADD_COMBO_NONE = "не задано"
BN_ADD_COMBO_BUTTON = "Задать…"
BN_ADD_BUTTON = "Добавить"
BN_CONFLICT_TITLE = "Сочетание {combo} уже занято"
BN_CONFLICT_BODY = "Сейчас на нём «{name}». Заменить? Прежний бинд отключится."
BN_CONFLICT_REPLACE = "Заменить"
BN_CONFLICT_CANCEL = "Отмена"
BN_SAME_COMBO = "Это то же сочетание"
BN_APPLYING = "Применяю…"
BN_DONE_REBIND = "«{name}»: теперь {combo}"
BN_DONE_DISABLE = "Отключено: {name}"
BN_DONE_REVERT = "Возвращено как было: {name}"
BN_DONE_ADD = "Добавлено: {combo}"
BN_NOTHING_CHANGED = "Ничего не изменилось"
BN_NOT_RELOADED = "Сохранено, но Hyprland не перечитал конфиг"
BN_FAILED = "Не удалось: {error}"
BN_CONFIG_ERRORS = "Hyprland нашёл ошибки, правка отменена: {errors}"
BN_LATER_FILE = "сочетание {combo} задаётся ещё и после settings-hub.conf ({where})"
BN_NO_BLOCK = "в {path} нет блока биндов settings-hub"

# History labels (one per user action; both combinations of a rebind share it).
BN_LABEL_REBIND = "Бинды: «{name}» → {combo}"
BN_LABEL_DISABLE = "Бинды: отключено «{name}»"
BN_LABEL_REVERT = "Бинды: вернуть «{name}»"
BN_LABEL_ADD = "Бинды: добавлено {combo}"

# Groups of the list, by group id (binds.names.group_of).
BN_GROUPS = {
    "apps": "Программы и команды",
    "windows": "Окна",
    "workspaces": "Рабочие столы",
    "device": "Клавиши звука и яркости",
    "mouse": "Мышь",
    "other": "Прочее",
    "submap": "Режим «{name}»",
    "disabled": "Отключённые",
    "live": "Только в живом Hyprland",
    "lua": "Бинды Hyprland",
}

# Key names. Modifiers in the order they are shown.
BN_MODS = {"SUPER": "Super", "CTRL": "Ctrl", "ALT": "Alt", "SHIFT": "Shift", "CAPS": "Caps",
           "MOD2": "Mod2", "MOD3": "Mod3", "MOD5": "Mod5"}
BN_KEY_JOIN = " + "
# Keysym names (lower case) -> what the user reads.
BN_KEYS = {
    "xf86audiomute": "Без звука",
    "xf86audiolowervolume": "Тише",
    "xf86audioraisevolume": "Громче",
    "xf86audiomicmute": "Микрофон",
    "xf86audioplay": "Пуск/пауза",
    "xf86audionext": "Следующий трек",
    "xf86audioprev": "Предыдущий трек",
    "xf86monbrightnessdown": "Яркость −",
    "xf86monbrightnessup": "Яркость +",
    "print": "Print Screen",
    "escape": "Esc",
    "return": "Enter",
    "space": "Пробел",
    "tab": "Tab",
    "backspace": "Backspace",
    "delete": "Delete",
    "left": "←",
    "right": "→",
    "up": "↑",
    "down": "↓",
    "page_up": "Page Up",
    "page_down": "Page Down",
    "home": "Home",
    "end": "End",
    "grave": "`",
    "comma": ",",
    "period": ".",
    "minus": "-",
    "equal": "=",
    "slash": "/",
    "backslash": "\\",
    "semicolon": ";",
    "apostrophe": "'",
    "bracketleft": "[",
    "bracketright": "]",
    "mouse:272": "Левая кнопка мыши",
    "mouse:273": "Правая кнопка мыши",
    "mouse:274": "Средняя кнопка мыши",
    "mouse_down": "Колесо вниз",
    "mouse_up": "Колесо вверх",
}
# code:N (a physical key, any layout) -> the key on a US keyboard.
BN_KEYCODES = {49: "`", 9: "Esc", 23: "Tab", 65: "Пробел"}
BN_KEYCODE = "Клавиша {code}"

# Names by dispatcher (and argument), when the config has no description or comment.
BN_DISPATCHERS = {
    "killactive": "Закрыть окно",
    "forcekillactive": "Убить окно",
    "togglefloating": "Плавающее окно",
    "fullscreen": "Во весь экран",
    "cyclenext": "Следующее окно",
    "bringactivetotop": "Поднять окно наверх",
    "pin": "Закрепить окно",
    "pseudo": "Псевдоплитка",
    "togglesplit": "Повернуть деление",
    "centerwindow": "Окно по центру",
    "togglegroup": "Группа окон",
    "exit": "Выйти из Hyprland",
    "focusurgentorlast": "Прошлое окно",
}
BN_DIRECTIONS = {"l": "влево", "r": "вправо", "u": "вверх", "d": "вниз"}
BN_WITH_ARG = {
    "workspace": "Стол {arg}",
    "movetoworkspace": "Перенести окно на стол {arg}",
    "movetoworkspacesilent": "Тихо перенести окно на стол {arg}",
    "togglespecialworkspace": "Особый стол {arg}",
    "movefocus": "Фокус {dir}",
    "movewindow": "Сдвинуть окно {dir}",
    "swapwindow": "Поменять окно {dir}",
    "resizeactive": "Размер окна {arg}",
    "submap": "Режим «{arg}»",
    "layoutmsg": "Лента: {arg}",
    "exec": "{arg}",
}
BN_WORKSPACE_STEPS = {
    "+1": "Следующий стол", "-1": "Предыдущий стол",
    "e+1": "Следующий занятый стол", "e-1": "Предыдущий занятый стол",
    "previous": "Прошлый стол",
}
BN_SUBMAP_RESET = "Выйти из режима"
BN_LAYOUTMSG = {
    "swapcol l": "Поменять с колонкой слева",
    "swapcol r": "Поменять с колонкой справа",
    "colresize -conf": "Окно в ленте уже",
    "colresize +conf": "Окно в ленте шире",
}
BN_MOUSE = {"movewindow": "Перетащить окно мышью", "resizewindow": "Тянуть размер окна мышью"}
# exec commands: the first pattern (a regular expression) found in the command wins.
BN_COMMANDS = (
    (r"screenshot\.sh\s+area", "Снимок области"),
    (r"screenshot\.sh\s+screen", "Снимок экрана"),
    (r"wallpaper\.sh\s+next", "Следующие обои"),
    (r"hub-wallpaper\.sh|settings-open\s+wallpaper", "Выбор обоев"),
    (r"settings-open\s+screen-sleep|screen-sleep/gui\.py", "Экран и сон"),
    (r"settings-open\b", "Настройки"),
    (r"hub-clipboard\.sh|cliphist", "История буфера обмена"),
    (r"/hub\.sh\b", "Меню (хаб)"),
    (r"rofi\s+-show\s+drun", "Список программ"),
    (r"wlogout", "Меню выключения"),
    (r"hyprshutdown|dispatch\s+exit", "Выход из сеанса"),
    (r"timer\.py", "Таймер"),
    (r"netspeed\.py", "Скорость интернета"),
    (r"spotlight", "Поиск"),
    (r"hyprpicker", "Пипетка"),
    (r"set-mute", "Без звука"),
    (r"set-volume.*%-", "Тише"),
    (r"set-volume.*%\+", "Громче"),
    (r"brightnessctl.*%-", "Темнее"),
    (r"brightnessctl.*%\+", "Светлее"),
    (r"handy", "Голосовой ввод"),
    (r"winmode\.py", "Режим «как Windows»"),
    (r"windows\.py", "Список окон"),
    (r"backup-manager", "Резервные копии"),
    (r"sysmon\.sh", "Монитор системы"),
    (r"^\S*kitty\b", "Терминал"),
    (r"^\S*(thunar|nautilus|dolphin)\b", "Файлы"),
    (r"^\S*(firefox|chromium|brave)\b", "Браузер"),
    (r"^\S*obsidian\b", "Obsidian"),
)
# A comment that starts with a key ("Ctrl + J: ...", "code:49 — ...") names the
# key; what follows the separator is the action. A comment that still talks about
# the key itself ("физическая клавиша...", "... hotkey") is not a name.
BN_KEY_WORDS = ("клавиш", "кнопк", "привязк", "hotkey", "shortcut", "keybind")
BN_NAME_MAX = 72
