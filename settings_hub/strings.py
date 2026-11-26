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
    "main": "Часто нужное",
    "display": "Экран и окна",
    "keyboard": "Клавиатура и мышь",
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
            "caffeine": ("Не засыпать", ["не засыпать", "не гасить", "кофеин", "бодрствовать"]),
            "ac": ("От сети", [
                "сон", "простой", "блокировка", "приглушить", "погасить", "зарядка", "питание",
                "пресет", "набор", "кино", "экономный", "обычный",
            ]),
            "battery": ("От батареи", [
                "сон", "простой", "блокировка", "приглушить", "погасить", "батарея", "питание",
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
        "title": "Обои",
        "keywords": [
            "обои", "фон", "картинка", "sddm", "блокировка",
        ],
        "rows": {
            "target": ("Куда ставить", [
                "рабочий стол", "экран блокировки", "экран входа", "все три", "цель",
            ]),
            "grid": ("Картинки", ["картинка", "фон", "миниатюры", "выбрать обои"]),
            "rofi": ("Открыть сетку rofi", ["rofi", "сетка", "пикер"]),
            "random": ("Случайные обои", ["случайные", "случайно", "перемешать", "каждый вход"]),
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
            "minimize": ("Сворачивание окон", [
                "свернуть", "сворачивание", "скрыть окно", "свёрнутые", "super+h", "кнопка",
                "рассыпается", "пиксели",
            ]),
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
            "redo": ("Вернуть отменённое", ["вернуть", "повторить", "вперёд", "ctrl+shift+z",
                                            "ctrl+y"]),
            "log": ("Журнал изменений", ["список", "правки"]),
        },
    },
}

# History page.
HISTORY_UNDO_GROUP = "Отменить"
HISTORY_UNDO_ROW = PAGES["history"]["rows"]["undo"][0]
HISTORY_UNDO_BUTTON = "Отменить"
HISTORY_UNDO_HINT = "Ctrl+Z в любом месте окна; ещё раз — шаг дальше назад"
HISTORY_REDO_ROW = PAGES["history"]["rows"]["redo"][0]
HISTORY_REDO_BUTTON = "Вернуть"
HISTORY_REDO_HINT = "Ctrl+Shift+Z: вернуть то, что отменил Ctrl+Z"
HISTORY_LOG_GROUP = "Изменения"
HISTORY_EMPTY = "Изменений пока нет"
HISTORY_UNDO_PREFIX = "Отмена"
HISTORY_UNDONE = "Отменено: {label}"
HISTORY_NOTHING_TO_UNDO = "Нечего отменять"
HISTORY_REDO_PREFIX = "Возврат"
HISTORY_REDONE = "Возвращено: {label}"
HISTORY_NOTHING_TO_REDO = "Нечего возвращать"
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
    "settings": "Настройки окна",
    "hypr": "Окна и ввод",
    "audio": "Звук",
    "network": "Сеть",
    "power": "Питание",
    "game-binds": "Игровые бинды",
    "themes": "Темы",
    "monitor": "Монитор",
    "notifications": "Уведомления",
    "autostart": "Автозапуск",
    "minimize_anim": "Сворачивание окон",
    "appearance": "Оформление",
}

# settings-open shows this when the window could not be started at all.
OPEN_FAILED = "Настройки не запустились, см. {log}"

# ---- Screen and sleep page -------------------------------------------------

SS_ROWS = PAGES["screen-sleep"]["rows"]
SS_ALERT_GROUP = "Не всё работает"
SS_POWER_NAMES = {"ac": "от сети", "battery": "от батареи"}
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
SS_IDLE_GROUP = "Простой"
SS_PROFILE_ROW = "Набор"
SS_SET_IN_FORCE = "Сейчас питание {power} — действует этот набор"
SS_SET_LATER = "Сейчас питание {power} — этот набор включится при смене питания"
SS_ORDER_OTHER = "В наборе «{profile}» шаги идут не по возрастанию времени"
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
SS_NIGHT_MORE = "Начало, выключение и цель"
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
WP_FAILED = "Не удалось: {error}"
WP_THUMBS = "Готовлю миниатюры: {n}"

# ---- Themes page -------------------------------------------------------------
# Theme ids and names (Catppuccin, Nord...) come from wallpaper-theme itself.

PAGES["themes"] = {
    "title": "Темы",
    "keywords": [
        "тема", "темы", "оформление", "цвета", "перекрасить", "вид", "внешний вид",
        "catppuccin", "nord", "gruvbox", "dracula", "rose pine", "everforest",
        "tokyo night", "one dark", "monochrome", "под обои", "яркий", "приглушённый",
    ],
    "rows": {
        "system": ("Тема системы", [
            "тема", "перекрасить всё", "одна кнопка", "сменить тему", "под обои", "яркий",
            "приглушённый", "интерфейс под обои",
        ]),
        "random": ("Случайная тема", ["случайная", "надоела", "другая тема"]),
        "walls": ("Менять обои вместе с темой", ["обои", "фон", "вместе"]),
        "theme-walls": ("Обои темы", ["обои темы", "картинки темы", "выбрать обои"]),
        "targets": ("Отдельно для программ", [
            "отдельно", "панель", "hyprpanel", "rofi", "kitty", "терминал", "рамки",
            "gtk", "блокировка", "своя тема программы",
        ]),
        "custom": ("Своя тема", ["своя", "создать тему", "цвет", "акцент"]),
    },
}
TH_ROWS = PAGES["themes"]["rows"]
TH_SYSTEM_GROUP = TH_ROWS["system"][0]
TH_SYSTEM_NOTE = ("Одно нажатие — и перекрашивается всё: панель, rofi, Настройки, kitty, "
                  "рамки окон, программы GTK и экран блокировки. Панель обновится за "
                  "несколько секунд, rofi — при следующем открытии, программы GTK — после "
                  "перезапуска.")
TH_RANDOM = TH_ROWS["random"][0]
TH_RANDOM_HINT = "Любая другая тема из списка"
TH_RANDOM_BUTTON = "Сменить"
TH_FROM_WALLPAPER = "из обоев"
TH_WALLS_GROUP = "Обои"
TH_WALLS = TH_ROWS["walls"][0]
TH_WALLS_HINT = ("Тема ставит свои обои на рабочий стол, блокировку и экран входа. "
                 "Случайные обои при входе — тоже только из обоев темы.")
TH_THEME_WALLS = TH_ROWS["theme-walls"][0]
TH_THEME_WALLS_HINT = "{n} из набора темы · {m} своих отмечено"
TH_THEME_WALLS_NONE = "У этой темы обоев нет — обои не меняются"
TH_THEME_WALLS_EDIT = "Выбрать свои"
TH_THEME_WALLS_DONE = "Готово"
TH_THEME_WALLS_NOTE = ("Нажми на картинку из своей библиотеки, чтобы добавить её к теме "
                       "или убрать.")
TH_TARGETS_GROUP = TH_ROWS["targets"][0]
TH_TARGETS_NOTE = "«Как у системы» — программа следует теме системы."
TH_TARGETS = {
    "panel": "Панель",
    "rofi": "Меню rofi",
    "settings": "Настройки",
    "kitty": "Терминал kitty",
    "borders": "Рамки окон",
    "gtk": "Программы GTK",
    "lock": "Экран блокировки",
}
TH_AS_SYSTEM = "Как у системы"
TH_CUSTOM_GROUP = TH_ROWS["custom"][0]
TH_CUSTOM_NOTE = ("Выбери три цвета: акцент (кнопки, выделение), фон и текст. Остальные "
                  "оттенки получатся сами. Новая тема появится среди карточек.")
TH_CUSTOM_NAME = "Название"
TH_CUSTOM_NAME_HINT = "Например: Моя синяя"
TH_CUSTOM_ACCENT = "Акцент"
TH_CUSTOM_BG = "Фон"
TH_CUSTOM_FG = "Текст"
TH_CUSTOM_SAVE = "Сохранить тему"
TH_CUSTOM_DELETE = "Удалить"
TH_CUSTOM_NO_NAME = "Сначала дай теме название"
TH_CUSTOM_SAVED = "Тема «{name}» сохранена"
TH_CUSTOM_DELETED = "Тема «{name}» удалена"
TH_MISSING = "wallpaper-theme не установлен"
TH_MISSING_HINT = "Ожидается {path}. Установить: ~/Projects/wallpaper-theme/install.sh"
TH_APPLYING = "Меняю тему…"
TH_DONE = "Тема: {name}"
TH_TARGET_DONE = "{target}: {name}"
TH_WALLS_ON = "Обои меняются вместе с темой"
TH_WALLS_OFF = "Обои больше не меняются вместе с темой"
TH_PARTLY = "Тема сменилась, но: {error}"
TH_FAILED = "Не удалось: {error}"
TH_LABEL_SYSTEM = "Тема системы"
TH_LABEL_WALLS = "Обои вместе с темой"
TH_LABEL_TARGET = "Тема: {target}"

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
MA_GROUP = AN_ROWS["minimize"][0]
MA_NOTE = "Как окно уходит по SUPER+H и возвращается кнопкой на панели."
MA_STYLE_ROW = "Анимация"
MA_PREVIEW_HINT = "Показать на этом окне: оно свернётся и сразу вернётся"
MA_SETUP_ERROR = "Не найдена программа свёрнутых окон (~/.local/share/minimize)"
MA_LABEL_STYLE = "Сворачивание окон: анимация"
MA_LABEL_SPEED = "Сворачивание окон: скорость"
MA_APPLIED = "Сворачивание: «{name}»"
MA_SPEED_APPLIED = "Сворачивание: {speed}"
MA_PREVIEW_NONE = "Без анимации показывать нечего"
MA_ERR_MISSING = "нет {path}"
MA_ERR_LOAD = "не загрузить {path}"
MA_ERR_NAME = "в {path} нет {name}"
MA_ERR_STYLE = "неизвестная анимация: {value}"
MA_ERR_SPEED = "неизвестная скорость: {value}"
MA_FAILED = "Не удалось сохранить: {error}"

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

# ---- General page: the window's own settings ---------------------------------

PAGES.update({
    "general": {
        "title": "Общие",
        "keywords": [
            "настройки окна", "общие", "тема окна", "анимация", "страница",
            "история", "поиск", "задержка", "миниатюры", "сайдбар", "размер окна",
        ],
        "rows": {},
    },
    "windows": {
        "title": "Окна и вид",
        "keywords": [
            "окна", "вид", "отступы", "рамка", "скругление", "прозрачность",
            "блюр", "размытие", "тень", "тени", "раскладка", "лента", "вкладки",
            "прилипание", "hyprland",
        ],
        "rows": {},
    },
    "input": {
        "title": "Клавиатура и мышь",
        "keywords": [
            "клавиатура", "мышь", "тачпад", "раскладка", "язык",
            "повтор", "прокрутка", "чувствительность", "касание", "num lock",
        ],
        "rows": {},
    },
    "appearance": {
        "title": "Оформление",
        "keywords": [
            "оформление", "шрифт", "шрифты", "размер текста", "масштаб текста", "значки",
            "иконки", "курсор", "указатель", "font", "icons", "крупнее", "мельче",
        ],
        "rows": {
            "font": ("Шрифт интерфейса", ["шрифт", "интерфейс", "font", "текст"]),
            "mono": ("Моноширинный шрифт", ["моноширинный", "код", "терминал", "mono"]),
            "scale": ("Размер текста", ["масштаб", "крупнее", "мельче", "размер текста"]),
            "icons": ("Значки", ["значки", "иконки", "icons", "тема значков"]),
            "panel_font": ("Шрифт панели", ["панель", "шрифт панели", "hyprpanel"]),
            "kitty_font": ("Шрифт терминала", ["kitty", "терминал", "шрифт терминала"]),
            "own_font": ("Шрифт этого окна", ["onest", "шрифт окна", "настройки"]),
        },
    },
})

HUB_GROUPS = {
    "appearance": "Внешний вид",
    "behavior": "Поведение",
    "advanced": "Дополнительно",
}
HUB_ADVANCED_HINT = "Задержки и размеры для тонкой подстройки; обычно трогать не нужно"

# key -> (label, hint, extra search words)
HUB_SETTINGS = {
    "appearance.theme": (
        "Тема окна", "Светлая, тёмная или как в системе",
        ["тема", "светлая", "тёмная", "системная", "оформление"]),
    "appearance.transition": (
        "Смена страниц", "Без анимации, плавное проявление или сдвиг",
        ["анимация", "переход", "страница", "плавно"]),
    "appearance.sidebar_width": (
        "Ширина сайдбара", "Полоски разделов слева, в точках",
        ["сайдбар", "ширина", "разделы", "меню"]),
    "appearance.highlight_ms": (
        "Подсветка из поиска", "Сколько строка подсвечена после перехода, мс",
        ["подсветка", "поиск", "строка"]),
    "appearance.status_ms": (
        "Сообщение внизу", "Сколько видно «Применено…», мс",
        ["сообщение", "статус", "внизу"]),
    "appearance.maximized": (
        "Открывать на весь экран", "Развёрнутым, верхняя панель остаётся видна",
        ["весь экран", "развернуть", "окно", "размер", "максимум"]),
    "appearance.window_width": (
        "Ширина окна", "Не на весь экран: с какой шириной открывается, точки",
        ["окно", "ширина", "размер"]),
    "appearance.window_height": (
        "Высота окна", "Не на весь экран: с какой высотой открывается, точки",
        ["окно", "высота", "размер"]),
    "appearance.remember_size": (
        "Запоминать размер окна", "Возвращаться к последнему размеру",
        ["размер", "окно", "запомнить"]),
    "appearance.own_font": (
        "Свой шрифт окна (Onest)",
        "Выключено — окно Настроек пишет шрифтом интерфейса со страницы «Оформление»",
        ["шрифт", "onest", "окно", "интерфейс"]),
    "behavior.start_page": (
        "Страница при открытии", "Куда попадать по SUPER+I",
        ["стартовая", "страница", "открытие", "super+i"]),
    "behavior.preload_s": (
        "Готовить страницы заранее", "Через сколько секунд, 0 — не готовить",
        ["предзагрузка", "страницы", "быстрее"]),
    "behavior.refresh_s": (
        "Обновлять «Экран и сон»", "Раз в сколько секунд, пока страница открыта",
        ["обновление", "перечитывание", "интервал"]),
    "behavior.history_keep": (
        "Хранить в Истории", "Сколько последних изменений",
        ["история", "журнал", "лимит", "записей"]),
    "behavior.apply_delay_ms": (
        "Задержка записи «Экран и сон»", "Через сколько после последней правки, мс",
        ["задержка", "запись", "таймаут"]),
    "behavior.night_slider_ms": (
        "Ночной ползунок: применение", "Живая смена температуры, мс",
        ["ползунок", "ночной", "температура"]),
    "behavior.series_still_ms": (
        "Ночной ползунок: конец серии", "Столько без движения — одна запись, мс",
        ["ползунок", "серия", "ночной"]),
    "behavior.guard_s": (
        "Защита поля от перезаписи", "«Экран и сон»: секунд после правки",
        ["защита", "перезапись", "поле"]),
    "behavior.search_limit": (
        "Результатов поиска", "Сколько строк показывать",
        ["поиск", "результаты", "строки"]),
}

HUB_CHOICES = {
    "system": "Как в системе",
    "light": "Светлая",
    "dark": "Тёмная",
    "none": "Без анимации",
    "fade": "Плавное проявление",
    "slide": "Сдвиг",
}

HUB_START_LAST = "Как в прошлый раз"
HUB_START_HOME = "Главная с плитками"
HUB_APPLIED = "Сохранено: {name}"
HUB_FAILED = "Не удалось сохранить: {error}"
HUB_NOTHING_CHANGED = "Всё уже по умолчанию"
HUB_RESET = "Вернуть настройки окна по умолчанию"
HUB_RESET_HINT = "Тема, страницы, задержки и лимиты — как при первой установке"
HUB_RESET_BUTTON = "Вернуть"
HUB_RESET_DONE = "Настройки окна вернулись к умолчаниям"

# ---- Variable pages: "Окна и вид" and "Клавиатура и мышь" --------------------

VAR_GROUPS = {
    "windows": {
        "gaps": "Отступы и рамки",
        "effects": "Эффекты",
        "layout": "Раскладка",
        "tabs": "Вкладки",
        "behavior": "Поведение",
    },
    "input": {
        "keyboard": "Клавиатура",
        "mouse": "Мышь",
        "touchpad": "Тачпад",
    },
    "appearance": {
        "cursor": "Курсор",
    },
}

# option -> (label, hint, extra search words)
VARS = {
    "general:gaps_in": ("Отступы между окнами", "Зазор между соседними окнами",
                        ["отступ", "зазор", "gaps"]),
    "general:gaps_out": ("Отступы от края экрана", "Поле вокруг рабочей области",
                         ["отступ", "край", "gaps"]),
    "general:border_size": ("Толщина рамки", "Рамка вокруг окна",
                            ["рамка", "граница", "border"]),
    "decoration:rounding": ("Скругление углов", "Радиус углов окна",
                            ["скругление", "углы", "rounding"]),
    "decoration:active_opacity": ("Прозрачность активного окна",
                                  "100 % — непрозрачное",
                                  ["прозрачность", "opacity", "активное"]),
    "decoration:inactive_opacity": ("Прозрачность остальных окон",
                                    "100 % — непрозрачные",
                                    ["прозрачность", "opacity", "неактивные"]),
    "decoration:dim_inactive": ("Затемнять неактивные окна", "Тусклый фон для фокуса",
                                ["затемнение", "dim", "неактивные"]),
    "decoration:dim_strength": ("Сила затемнения", "Насколько темнее неактивные",
                                ["затемнение", "сила"]),
    "decoration:blur:enabled": ("Размытие фона", "Блюр под прозрачными окнами",
                                ["блюр", "размытие", "blur"]),
    "decoration:blur:size": ("Радиус размытия", "Больше — мягче",
                             ["блюр", "радиус", "blur"]),
    "decoration:blur:passes": ("Проходов размытия", "Больше — качественнее и дороже",
                               ["блюр", "проходы"]),
    "decoration:blur:ignore_opacity": ("Размывать прозрачные окна",
                                       "Не учитывать прозрачность окна",
                                       ["блюр", "прозрачность"]),
    "decoration:blur:xray": ("Размывать перекрытые окна", "Размытие насквозь (xray)",
                             ["блюр", "xray", "перекрытые"]),
    "decoration:shadow:enabled": ("Тени окон", "Тень под окнами",
                                  ["тень", "тени", "shadow"]),
    "decoration:shadow:range": ("Размер тени", "Насколько далеко расходится",
                                ["тень", "размер"]),
    "general:layout": ("Раскладка окон", "Как Hyprland раскладывает окна",
                       ["раскладка", "layout", "лента", "dwindle"]),
    "dwindle:preserve_split": ("Сохранять деление", "Деление не меняется само",
                               ["деление", "dwindle", "split"]),
    "dwindle:force_split": ("Куда ставить новое окно", "Сторона нового окна",
                            ["деление", "новое окно", "split"]),
    "dwindle:smart_split": ("Умное деление", "Учитывать место под окном",
                            ["деление", "умное"]),
    "scrolling:column_width": ("Ширина колонки в ленте", "Доля экрана, 0.5 — половина",
                               ["лента", "колонка", "ширина", "scrolling"]),
    "scrolling:wrap_focus": ("Фокус по кругу", "С края ленты на другой край",
                             ["лента", "фокус", "круг"]),
    "scrolling:wrap_swapcol": ("Перестановка по кругу", "Колонка с края уходит в конец",
                               ["лента", "перестановка", "колонка"]),
    "scrolling:fullscreen_on_one_column": ("Во весь экран при одной колонке",
                                           "Одна колонка занимает всё",
                                           ["лента", "полный экран"]),
    "general:snap:enabled": ("Прилипание плавающих окон", "Окна цепляются к краям",
                             ["прилипание", "snap", "плавающие"]),
    "general:snap:window_gap": ("Зазор между окнами", "При прилипании",
                                ["прилипание", "зазор"]),
    "general:snap:monitor_gap": ("Зазор до края экрана", "При прилипании",
                                 ["прилипание", "край"]),
    "group:auto_group": ("Новое окно сразу вкладкой", "Автоматические вкладки",
                         ["вкладки", "группа", "авто"]),
    "group:insert_after_current": ("Вкладка после текущей", "Порядок вкладок",
                                   ["вкладки", "порядок"]),
    "group:groupbar:render_titles": ("Подписи вкладок", "Показывать названия",
                                     ["вкладки", "подписи"]),
    "group:groupbar:gradients": ("Градиент панели вкладок", "Цвет панели",
                                 ["вкладки", "градиент", "цвет"]),
    "group:groupbar:stacked": ("Вкладки стопкой", "Панель вкладок столбиком",
                               ["вкладки", "стопка"]),
    "group:groupbar:font_size": ("Размер шрифта вкладок", "Точек",
                                 ["вкладки", "шрифт"]),
    "group:groupbar:height": ("Высота панели вкладок", "Точек",
                              ["вкладки", "высота"]),
    "misc:focus_on_activate": ("Фокус по запросу окна", "Окно само забирает фокус",
                               ["фокус", "активация"]),
    "misc:animate_manual_resizes": ("Анимация ручного размера", "Плавно при перетаскивании",
                                    ["анимация", "размер"]),
    "misc:animate_mouse_windowdragging": ("Анимация перетаскивания мышью",
                                          "Плавно при перетаскивании",
                                          ["анимация", "перетаскивание"]),
    "misc:mouse_move_enables_dpms": ("Движение мыши будит экран", "Не гасить при движении",
                                     ["пробуждение", "dpms", "мышь"]),
    "misc:key_press_enables_dpms": ("Клавиша будит экран", "Не гасить при нажатии",
                                    ["пробуждение", "dpms", "клавиатура"]),
    "misc:disable_hyprland_logo": ("Без логотипа Hyprland", "Не рисовать логотип на фоне",
                                   ["логотип", "фон"]),
    "input:kb_layout": ("Раскладки", "Через запятую: us,ru,no. Enter — применить",
                        ["раскладка", "язык", "клавиатура"]),
    "input:kb_options": ("Настройки раскладки", "Например grp:win_space_toggle. Enter — применить",
                         ["раскладка", "переключение", "язык"]),
    "input:repeat_delay": ("Задержка повтора", "До начала повтора, мс",
                           ["повтор", "задержка", "клавиша"]),
    "input:repeat_rate": ("Частота повтора", "Символов в секунду",
                          ["повтор", "частота", "клавиша"]),
    "input:numlock_by_default": ("Num Lock при входе", "Включать Num Lock",
                                 ["numlock", "numpad"]),
    "input:natural_scroll": ("Обратная прокрутка мыши", "Направление колеса наоборот",
                             ["прокрутка", "мышь", "направление"]),
    "input:sensitivity": ("Чувствительность мыши", "0 — как есть, минус — медленнее",
                          ["чувствительность", "мышь", "скорость"]),
    "input:follow_mouse": ("Фокус за мышью", "Когда окно получает фокус",
                           ["фокус", "мышь", "наведение"]),
    "input:touchpad:natural_scroll": ("Обратная прокрутка тачпада",
                                      "Направление двумя пальцами",
                                      ["тачпад", "прокрутка", "направление"]),
    "input:touchpad:tap-to-click": ("Касание = клик", "Клик без нажатия",
                                    ["тачпад", "касание", "клик"]),
    "input:touchpad:disable_while_typing": ("Не реагировать при наборе",
                                            "Защита от случайных касаний",
                                            ["тачпад", "набор", "печать"]),
    "input:touchpad:clickfinger_behavior": ("Клик пальцами", "Число пальцев задаёт кнопку",
                                            ["тачпад", "клик", "пальцы"]),
    "input:touchpad:scroll_factor": ("Скорость прокрутки тачпада", "Множитель",
                                     ["тачпад", "прокрутка", "скорость"]),
    "cursor:theme": ("Тема курсора", "Для новых окон; перезаход — для всех",
                     ["курсор", "тема", "стрелка"]),
    "cursor:size": ("Размер курсора", "Точек",
                    ["курсор", "размер"]),
}

CHOICE_LABELS = {
    "dwindle": "Dwindle: деление",
    "master": "Master: главное окно",
    "scrolling": "Лента (scrolling)",
}

VAR_CHOICES = {
    "dwindle:force_split": {"0": "По умолчанию", "1": "Слева/сверху",
                            "2": "Справа/снизу"},
    "input:follow_mouse": {"0": "Выключен", "1": "Полный", "2": "Половина",
                           "3": "Только окно"},
}

VAR_APPLIED = "Применено: {name}"
VAR_APPLY_FAILED = "Не удалось применить: {error}"
VAR_READ_FAILED = "Не удалось прочитать значения Hyprland: {error}"
VAR_RESET = "Вернуть значения из конфига"
VAR_RESET_HINT = "Забыть правки этого окна: hyprland.lua снова решает, после перечитывания"
VAR_RESET_BUTTON = "Вернуть"
VAR_RESET_ASK = "Все правки этой страницы будут забыты. Отменить можно через Ctrl+Z или «Историю»."
VAR_EMPTY_LAYOUT = "Раскладка не может быть пустой"
VAR_NOT_READ = "Значение ещё не прочитано, изменить пока нельзя"
VAR_NOT_TAKEN = "Hyprland оставил другое значение: {name} = {value}"
VAR_RESET_DONE = "Значения снова из конфига"



# ---- Sound page --------------------------------------------------------------

PAGES.update({
    "sound": {
        "title": "Звук",
        "keywords": ["звук", "громкость", "колонки", "наушники", "микрофон",
                     "устройство", "выход", "вход", "mute", "глухо"],
        "rows": {
            "sink.device": ("Выход: устройство", ["выход", "колонки", "наушники",
                                                  "устройство", "по умолчанию"]),
            "sink.volume": ("Громкость", ["громкость", "тише", "громче", "проценты"]),
            "sink.mute": ("Без звука", ["mute", "глухо", "выключить звук"]),
            "source.device": ("Вход: устройство", ["микрофон", "вход", "устройство"]),
            "source.volume": ("Громкость микрофона", ["микрофон", "громкость"]),
            "source.mute": ("Микрофон без звука", ["микрофон", "mute", "глухо"]),
            "apps": ("Громкость программ", ["микшер", "программы", "приложения", "firefox",
                                            "громкость программы", "тише программу"]),
            "recorders": ("Кто слушает микрофон", ["микрофон", "запись", "слушает",
                                                    "приватность"]),
        },
    },
})

AUDIO_KINDS = {"sink": "выход", "source": "вход"}
AUDIO_APPS_GROUP = "Программы"
AUDIO_APPS_NONE = "Сейчас ни одна программа не играет звук"
AUDIO_APP_PAUSED = "на паузе"
AUDIO_APP_MUTE = "Без звука"
AUDIO_APP_MUTE_TIP = "Выключить звук только этой программы"
AUDIO_APP_GONE = "«{app}» уже не играет звук"
AUDIO_LABEL_APP_VOLUME = "Громкость: {app}"
AUDIO_LABEL_APP_MUTE = "Без звука: {app}"
AUDIO_RECORDERS = "Микрофон слушают"
AUDIO_RECORDERS_NONE = "Сейчас микрофон никто не слушает"
AUDIO_GROUP_OUT = "Выход"
AUDIO_GROUP_IN = "Вход"
AUDIO_DEVICE = "Устройство"
AUDIO_VOLUME = "Громкость"
AUDIO_MUTE = "Без звука"
AUDIO_PERCENT = "{percent}%"
AUDIO_NO_DEVICES = "Нет устройств"
AUDIO_VOLUME_DONE = "громкость {percent}%"
AUDIO_DEFAULT_SINK = "Звук: устройство вывода"
AUDIO_DEFAULT_SOURCE = "Звук: устройство ввода"
AUDIO_LABEL_VOLUME = "Звук: громкость ({kind})"
AUDIO_LABEL_MUTE = "Звук: без звука ({kind})"
AUDIO_APPLIED = "Применено: {name}"
AUDIO_APPLY_FAILED = "Не удалось: {error}"
AUDIO_READ_FAILED = "Не удалось прочитать звук: {error}"

# ---- Network page ------------------------------------------------------------

PAGES.update({
    "network": {
        "title": "Сеть и Bluetooth",
        "keywords": ["сеть", "wi-fi", "wifi", "вайфай", "bluetooth", "блютуз",
                     "интернет", "tailscale", "подключение", "роутер"],
        "rows": {
            "wifi.radio": ("Wi-Fi", ["wi-fi", "wifi", "радио", "включить", "выключить"]),
            "wifi.current": ("Текущая сеть", ["сеть", "подключение", "сигнал"]),
            "wifi.saved": ("Сохранённые сети", ["сеть", "подключить", "сохранённые"]),
            "wifi.hidden": ("Скрытая сеть", ["скрытая", "сеть", "пароль", "подключить",
                                             "ssid"]),
            "wifi.visible": ("Подключиться к новой сети", ["пароль", "подключить", "новая сеть",
                                                           "видимые сети", "wi-fi"]),
            "bluetooth.power": ("Bluetooth", ["bluetooth", "блютуз", "радио"]),
            "bluetooth.devices": ("Bluetooth-устройства", ["наушники", "airpods", "колонка",
                                                           "мышь", "подключить", "отключить",
                                                           "забыть"]),
            "bluetooth.search": ("Найти Bluetooth-устройство", ["сопряжение", "найти",
                                                                "новое устройство", "pair"]),
            "tailscale": ("Tailscale", ["tailscale", "vpn", "сеть", "адрес"]),
        },
    },
})

NET_WIFI_GROUP = "Wi-Fi"
NET_WIFI = "Wi-Fi"
NET_WIFI_HINT = "Радио Wi-Fi: выключить или включить"
NET_STILL_CONNECTING = "Подключение к «{name}» ещё идёт, страница покажет итог"
NET_NOT_READ = "не удалось узнать, какая сеть подключена"
NET_WIFI_OFF_ASK = "Выключить Wi-Fi?"
NET_WIFI_OFF_DETAIL = "Интернет и Tailscale могут пропасть, если другого подключения нет."
NET_WIFI_OFF_OK = "Выключить"
NET_WIFI_CURRENT = "Текущая сеть"
NET_WIFI_SIGNAL = "{ssid} · {signal}%"
NET_WIFI_OFF = "Выключено"
NET_WIFI_NONE = "Не подключено"
NET_SAVED_GROUP = "Сохранённые сети"
NET_SAVED_EMPTY = "Сохранённых сетей нет"
NET_SAVED_ACTIVE = "Подключено"
NET_SAVED_OFF = "Не подключено"
NET_CONNECT = "Подключить"
NET_VISIBLE_GROUP = "Видимые сети"
NET_VISIBLE = "{ssid}"
NET_VISIBLE_DETAIL = "сигнал {signal}% · {security}"
NET_OPEN_SUFFIX = " (открытая)"
NET_JOIN = "Подключить"
NET_JOINING = "Подключаю…"
NET_JOIN_PASSWORD = "Пароль сети"
NET_JOIN_NO_NM = "NetworkManager не отвечает"
NET_JOIN_PASSWORD_HINT = "Пароль от «{ssid}»"
NET_JOIN_SSID = "Имя сети"
NET_JOIN_STARTED = "Подключаю к «{ssid}»…"
NET_JOIN_DONE = "Подключено: {name}"
NET_JOIN_FAILED_STATUS = "Не подключилось: {error}"
NET_JOIN_NO_DEVICE = "нет Wi-Fi адаптера"
NET_JOIN_NOT_VISIBLE = "сеть «{ssid}» сейчас не видна"
NET_JOIN_NO_NAME = "не указано имя сети"
NET_JOIN_LONG_NAME = "имя сети длиннее 32 байт"
NET_JOIN_UNSUPPORTED = "сети с логином (802.1X) и старые WEP пока не поддерживаются"
NET_JOIN_UNSUPPORTED_TIP = "Сети с логином (802.1X) и старые WEP пока не поддерживаются"
NET_JOIN_PASSWORD_LENGTH = ("пароль Wi-Fi — от 8 до 63 латинских букв, цифр и знаков "
                            "(или ключ из 64 знаков 0-9, a-f)")
NET_JOIN_NO_KIND = "не известна защита сети — обновите список и попробуйте снова"
NET_VISIBLE_MIXED = " · ⚠ есть точки с этим именем и другой защитой"
NET_JOIN_SECURITY_CHANGED = ("сеть «{ssid}» сейчас видна с другой защитой, чем в списке — "
                             "не подключаю (возможно, чужая точка с тем же именем)")
NET_JOIN_HIDDEN_NEEDS_PASSWORD = "для скрытой сети нужен пароль"
NET_JOIN_DONE_UNSAVED = "Подключено: {name}, но не сохранилось на следующий запуск"
NET_JOIN_BUSY = "уже идёт другое подключение — подождите"
NET_JOIN_UNEXPECTED = "непредвиденная ошибка ({kind}), подробности в журнале"
NET_JOIN_REFUSED = "NetworkManager отказал: {error}"
NET_JOIN_BAD_PASSWORD = "неверный пароль"
NET_JOIN_TIMEOUT = "сеть не ответила за 30 секунд"
NET_JOIN_FAILED = "ошибка NetworkManager (код {code})"
NET_HIDDEN = "Скрытая сеть"
NET_HIDDEN_HINT = "Сеть, которая не показывает своё имя"
NET_HIDDEN_BUTTON = "Подключить…"
NET_BLUETOOTH_GROUP = "Bluetooth"
NET_BLUETOOTH = "Bluetooth"
NET_BLUETOOTH_HINT = "Радио Bluetooth: выключить или включить"
NET_BT_CONNECTED = "Подключено"
NET_BT_NONE = "Нет подключённых устройств"
BT_MY_DEVICES_NONE = "Сопряжённых устройств нет — найдите новое ниже"
BT_CONNECTED = "Подключено"
BT_NOT_CONNECTED = "Не подключено"
BT_BATTERY = " · заряд {percent}%"
BT_CONNECT = "Подключить"
BT_DISCONNECT = "Отключить"
BT_WORKING = "Подождите…"
BT_FORGET = "Забыть"
BT_FORGET_TIP = "Удалить сопряжение: чтобы подключить снова, устройство придётся найти заново"
BT_FORGET_ASK = "Забыть «{name}»?"
BT_FORGET_DETAIL = "Чтобы подключить его снова, понадобится режим сопряжения на самом устройстве."
BT_SEARCH = "Найти новое устройство"
BT_SEARCH_HINT = "Переведите устройство в режим сопряжения, поиск идёт {seconds} с"
BT_SEARCH_BUTTON = "Искать"
BT_SEARCH_STOP = "Остановить"
BT_SEARCHING = "Ищу…"
BT_FOUND_NONE = "Пока ничего не найдено"
BT_FOUND_DETAIL = "{kind} · {address}"
BT_KINDS = {
    "audio-headphones": "наушники",
    "audio-headset": "гарнитура",
    "audio-card": "колонка",
    "audio": "звук",
    "input-mouse": "мышь",
    "input-keyboard": "клавиатура",
    "input-gaming": "геймпад",
    "input-tablet": "планшет для рисования",
    "phone": "телефон",
    "computer": "компьютер",
    "camera": "камера",
    "printer": "принтер",
}
BT_KIND_UNKNOWN = "тип неизвестен"
BT_PAIR_ASK = "Подключить «{name}»?"
BT_PAIR_DETAIL = ("Тип: {kind}, адрес {address}.\nУстройство запомнится и сможет "
                  "подключаться само. Имя назначает само устройство — подключайте, "
                  "только если это ваше и оно рядом в режиме сопряжения.")
BT_PAIR_DETAIL_RISKY = ("Тип: {kind}, адрес {address}.\nЭто не просто звук (устройство ввода, "
                        "телефон, компьютер или тип неизвестен): оно сможет печатать и "
                        "нажимать за вас и будет "
                        "подключаться само. Имя назначает само устройство, его легко "
                        "подделать. Подключайте, только если это точно ваше устройство "
                        "и вы видите его рядом в режиме сопряжения.")
BT_PAIR = "Подключить"
BT_DONE_CONNECT = "Подключено: {name}"
BT_DONE_DISCONNECT = "Отключено: {name}"
BT_DONE_FORGET = "Забыто: {name}"
BT_DONE_PAIR = "Сопряжено и подключено: {name}"
BT_FAILED = "{name}: {error}"
BT_NO_DEVICES_LIST = "Список Bluetooth-устройств недоступен"
BT_ERR_AUTH = "устройство не приняло сопряжение (если оно просит код — это пока не поддерживается)"
BT_ERR_TIMEOUT = "устройство не ответило вовремя"
BT_ERR_UNREACHABLE = "устройство не отвечает — оно включено и рядом?"
BT_ERR_FAILED = "не получилось (устройство занято другим телефоном или выключено?)"
BT_ERR_BUSY = "уже идёт другое действие"
BT_ERR_ALREADY = "уже сопряжено"
BT_ERR_OFF = "Bluetooth выключен"
BT_ERR_GONE = "устройство пропало из списка"
BT_ERR_NO_BLUEZ = "служба Bluetooth не запущена"
BT_ERR_OTHER = "ошибка Bluetooth: {error}"
BT_ERR_IS_INPUT = ("оно оказалось устройством ввода (может печатать за вас) — "
                   "забыто; если это ваше, подключите снова и согласитесь с предупреждением")
NET_TAILSCALE_GROUP = "Tailscale"
NET_TAILSCALE = "Tailscale"
NET_TAILSCALE_STATE = "{state} · {addresses}"
NET_NO_IP = "без адресов"
NET_UNKNOWN = "неизвестно"
NET_LABEL_WIFI = "Сеть: Wi-Fi"
NET_LABEL_BLUETOOTH = "Сеть: Bluetooth"
NET_LABEL_CONNECTION = "Сеть: подключение"
NET_APPLIED = "Применено: {name}"
NET_APPLY_FAILED = "Не удалось: {error}"
NET_READ_FAILED = "Не удалось прочитать сеть: {error}"

# ---- Power page --------------------------------------------------------------

PAGES.update({
    "power": {
        "title": "Питание и яркость",
        "keywords": ["питание", "батарея", "заряд", "яркость", "экран",
                     "профиль", "энергия", "аккумулятор", "износ"],
        "rows": {
            "battery.charge": ("Заряд", ["батарея", "заряд", "процент"]),
            "battery.status": ("Состояние батареи", ["заряжается", "разряжается"]),
            "battery.health": ("Ёмкость батареи", ["износ", "ёмкость", "здоровье"]),
            "battery.cycles": ("Циклы", ["циклы", "износ"]),
            "battery.ac": ("Питание", ["сеть", "зарядка", "адаптер"]),
            "profile": ("Профиль питания", ["профиль", "производительность",
                                            "экономия", "энергия"]),
            "brightness": ("Яркость", ["яркость", "экран", "подсветка"]),
            "devices": ("Заряд мыши и наушников", [
                "мышь", "наушники", "bluetooth", "блютуз", "airpods", "заряд",
                "батарея", "устройства", "гарнитура"]),
        },
    },
})

POWER_BATTERY = "Батарея"
POWER_CHARGE = "Заряд"
POWER_STATUS = "Состояние"
POWER_HEALTH = "Ёмкость"
POWER_HEALTH_HINT = "Сейчас и при покупке"
POWER_HEALTH_VALUE = "{percent}% · {full} из {design} Вт·ч"
POWER_CYCLES = "Циклы"
POWER_AC = "Питание"
POWER_AC_ON = "от сети"
POWER_AC_OFF = "от батареи"
POWER_PROFILE = "Питание"
POWER_PROFILE_ROW = "Профиль питания"
POWER_PROFILE_HINT = "Производительность, обычный или экономия"
POWER_PROFILES = {
    "performance": "Производительность",
    "balanced": "Обычный",
    "power-saver": "Экономия",
}
POWER_SCREEN = "Экран"
POWER_BRIGHTNESS = "Яркость"
POWER_PERCENT = "{percent}%"
POWER_NO_BATTERY = "Батареи нет"
POWER_STATES = {
    "Full": "Заряжена",
    "Charging": "Заряжается",
    "Discharging": "Разряжается",
    "Not charging": "Не заряжается",
    "Unknown": "Неизвестно",
}
POWER_LABELS = {"power.profile": "Питание: профиль", "power.brightness": "Питание: яркость"}
POWER_APPLIED = "Применено: {name}"
POWER_APPLY_FAILED = "Не удалось: {error}"
POWER_READ_FAILED = "Не удалось прочитать питание: {error}"
POWER_DEVICES = "Мышь и наушники"
POWER_DEVICES_NOTE = ("Предупрежу уведомлением, когда заряд опустится до 20% и до 5%. "
                      "Наушники Bluetooth видны, только пока подключены.")
POWER_DEVICES_LOOKING = "Ищу устройства…"
POWER_DEVICES_NONE = "Устройств с батареей не видно"
POWER_DEVICES_NONE_HINT = "Включите мышь или подключите наушники"
POWER_DEVICE_KINDS = {"mouse": "Мышь", "headphones": "Наушники", "keyboard": "Клавиатура"}
# Word stems in a device's own name that tell its kind (lower case).
DEVICE_WORDS = {"mouse": ("мыш",), "keyboard": ("клавиат",)}
UNIT_MS = "мс"
POWER_DEVICE_CHARGING = "заряжается"
POWER_DEVICE_ASLEEP = "спит — последнее значение"
POWER_DEVICE_UNREADABLE = "не читается"
POWER_DEVICE_UNREADABLE_HINT = "Через USB-приёмник наушники заряд не передают — только по Bluetooth"
POWER_DEVICE_UNREADABLE_OTHER = "Устройство не сообщает заряд"
POWER_LOW_TITLE = "{name}: заряд {percent}%"
POWER_LOW_BODY = {20: "Пора зарядить.", 5: "Скоро выключится — зарядите сейчас."}

# ---- System page -------------------------------------------------------------

PAGES.update({
    "system": {
        "title": "Система",
        "keywords": ["система", "компьютер", "о компьютере", "об этом", "ядро",
                     "процессор", "память", "диск", "температура", "обновления",
                     "службы", "uptime"],
        "rows": {
            "model": ("Компьютер", ["ноутбук", "модель", "производитель"]),
            "hostname": ("Имя", ["имя", "хост", "hostname"]),
            "os": ("Система", ["arch", "linux", "версия", "дистрибутив"]),
            "kernel": ("Ядро", ["ядро", "kernel"]),
            "hyprland": ("Композитор", ["hyprland", "версия"]),
            "cpu": ("Процессор", ["процессор", "cpu", "ядра", "потоки"]),
            "memory": ("Память", ["оперативная", "ram", "озу", "подкачка"]),
            "disk": ("Диск", ["диск", "место", "свободно"]),
            "temperature": ("Температура", ["температура", "нагрев", "градусы"]),
            "uptime": ("Время работы", ["время", "аптайм", "uptime"]),
            "failed": ("Упавшие службы", ["службы", "systemd", "ошибки"]),
            "updates": ("Обновления", ["обновления", "pacman", "пакеты"]),
        },
    },
})

SYS_ABOUT_GROUP = "Об этом компьютере"
SYS_STATE_GROUP = "Состояние"
SYS_TITLES = {
    "model": "Компьютер",
    "hostname": "Имя",
    "os": "Система",
    "kernel": "Ядро",
    "hyprland": "Композитор",
    "cpu": "Процессор",
    "memory": "Память",
    "disk": "Диск",
    "temperature": "Температура процессора",
    "uptime": "Время работы",
}
SYS_MODEL = SYS_TITLES["model"]
SYS_HOSTNAME = SYS_TITLES["hostname"]
SYS_OS = SYS_TITLES["os"]
SYS_KERNEL = SYS_TITLES["kernel"]
SYS_HYPRLAND = SYS_TITLES["hyprland"]
SYS_CPU = SYS_TITLES["cpu"]
SYS_MEMORY = SYS_TITLES["memory"]
SYS_DISK = SYS_TITLES["disk"]
SYS_TEMPERATURE = SYS_TITLES["temperature"]
SYS_UPTIME = SYS_TITLES["uptime"]
SYS_CORES = "{cores} потоков"
SYS_MEMORY_VALUE = "{used} из {total} ГБ · {percent}%"
SYS_SWAP = "Подкачка: {used} из {total} ГБ"
SYS_DISK_VALUE = "{used} из {total} ГБ · {percent}%"
SYS_DISK_FREE = "Свободно {free} ГБ"
SYS_TEMPERATURE_VALUE = "{celsius:.1f} °C"
SYS_UPTIME_HM = "{hours} ч {minutes} мин"
SYS_UPTIME_DMY = "{days} д {hours} ч {minutes} мин"
SYS_FAILED = "Упавшие службы"
SYS_FAILED_OK = "Упавших служб нет"
SYS_FAILED_BAD = "Упавших служб: {count}"
SYS_UPDATES = "Обновления"
SYS_UPDATES_N = "По последней проверке ждут обновления: {count}"
SYS_UPDATES_OK = "Проверить и обновить — на странице «Обновления»"
SYS_UPDATES_OPEN = "Открыть"
SYS_REFRESH = "Проверить снова"
SYS_REFRESH_HINT = "Перечитать сведения о компьютере"
SYS_READ_FAILED = "Не удалось прочитать сведения: {error}"

# ---- Modes page --------------------------------------------------------------

PAGES.update({
    "modes": {
        "title": "Режимы",
        "keywords": ["режим", "профиль", "игра", "работа", "ночь", "дорога",
                     "одним нажатием", "набор"],
        "rows": {
            "work": ("Работа", ["работа", "офис", "обычный"]),
            "game": ("Игра", ["игра", "игры", "fps", "производительность"]),
            "night": ("Ночь", ["ночь", "вечер", "тёплый", "фильтр"]),
            "travel": ("В дороге", ["дорога", "батарея", "экономия", "поездка"]),
        },
    },
})

MODES_GROUP = "Готовые режимы"
MODES = {
    "work": (
        "Работа",
        "Отступы, скругления и блюр, обычный профиль питания, яркость 85 %, "
        "ночной фильтр по расписанию", ["работа", "офис"]),
    "game": (
        "Игра",
        "Без отступов и эффектов, производительность, яркость 100 %, "
        "ночной фильтр выключен", ["игра", "fps", "производительность"]),
    "night": (
        "Ночь",
        "Тёплый ночной фильтр 3200 K, яркость 30 %, приглушённые неактивные окна",
        ["ночь", "вечер", "тёплый"]),
    "travel": (
        "В дороге",
        "Экономия энергии, яркость 45 %, без блюра, узкие отступы",
        ["дорога", "батарея", "экономия"]),
}
MODE_APPLY = "Включить"
MODE_TURN_OFF = "Выключить"
MODE_IS_ON = "включён"
MODES_NOTE = "Как это работает"
MODES_NOTE_HINT = ("Режим меняет отступы, эффекты, яркость, профиль питания и ночной "
                   "фильтр одним действием. «Выключить» возвращает всё, как было до "
                   "режима; ещё можно Ctrl+Z или «История».")
MODE_APPLIED = "Режим «{name}» включён"
MODE_FAILED = "Не удалось применить режим: {error}"
MODE_NO_APPLIER = "нет обработчика"
MODE_ITEMS = {
    "night.manual_override": "Ночной фильтр: расписание",
    "night.current_temp": "Ночной фильтр: температура",
}

# ---- History page additions --------------------------------------------------

HISTORY_ALL = "Все изменения"
HISTORY_FILTER = "Показывать"
HISTORY_FILTER_HINT = "Только изменения выбранного раздела"
HISTORY_RETURN = "Вернуть"
HISTORY_RETURN_TITLE = "Вернуть на этот момент?"
HISTORY_RETURN_BODY = "Все изменения после «{label}» будут отменены."
HISTORY_RETURN_OK = "Вернуть"
HISTORY_EMPTY_FILTER = "В этом разделе изменений нет"
HISTORY_EXPORT = "Сохранить журнал"
HISTORY_EXPORT_HINT = "Рядом с журналом появится history-export.jsonl"
HISTORY_EXPORT_BUTTON = "Сохранить"
HISTORY_EXPORTED = "Журнал сохранён: {path} ({count} записей)"
HISTORY_EXPORT_FAILED = "Не удалось сохранить журнал: {error}"
HISTORY_NOTHING_LATER = "После этого момента изменений нет"

# ---- Game binds page ---------------------------------------------------------

PAGES["game-binds"] = {
    "title": "Игровые бинды",
    "keywords": ["игра", "игры", "дота", "dota", "steam", "бинды", "клавиши",
                 "сочетания", "отключить", "игровой режим"],
    "rows": {
        "enabled": ("Отключать бинды в играх", ["вкл", "включить", "игровой режим"]),
        "games": ("Игры", ["окно", "класс", "шаблон", "дота", "steam"]),
        "combos": ("Отключаемые сочетания", ["бинды", "клавиши", "super", "сочетание"]),
    },
}

GB_LABEL = "Игровые бинды"
GB_MODE = "Игровой режим"
GB_MODE_NOTE = ("Пока окно игры в фокусе, выбранные сочетания достаются игре, а не "
                "Hyprland. Как только фокус уходит из игры, они снова работают. "
                "Работает и при закрытом окне настроек.")
GB_ENABLED = "Отключать бинды в играх"
GB_GAMES = "Игры"
GB_GAMES_NOTE = ("Окно считается игрой по своему классу. * — любой текст, ? — один "
                 "символ: steam_app_* — все игры из Steam.")
GB_NO_GAMES = "Список пуст — ни одно окно не считается игрой"
GB_REMOVE = "Убрать"
GB_FROM_OPEN = "Из открытых окон"
GB_FROM_OPEN_HINT = "Запустите игру, вернитесь сюда и выберите её окно"
GB_NO_OPEN = "Нет подходящих окон"
GB_OWN_PATTERN = "Свой шаблон"
GB_OWN_PATTERN_PLACEHOLDER = "например, cs2 или *minecraft*"
GB_ADD = "Добавить"
GB_COMBOS = "Отключаемые сочетания"
GB_COMBOS_NOTE = "Сочетание без назначения тоже можно добавить: тогда отключать нечего."
GB_NO_COMBOS = "Список пуст — в играх ничего не отключается"
GB_ACTION_NONE = "Сейчас ни на что не назначено"
GB_ACTION_NO_TEXT = "Назначено (без описания)"
GB_ADD_COMBO = "Добавить сочетание"
GB_PRESS = "Нажать сочетание"
GB_PRESSING = "Нажмите сочетание… (Esc — отмена)"
GB_NOT_LOADED = ("Hyprland пока не читает этот список: переустановите настройки "
                 "(install.sh), затем включите снова.")
GB_DONE_ON = "Игровой режим включён"
GB_DONE_OFF = "Игровой режим выключен"
GB_DONE_PATTERN_ADDED = "Добавлена игра: {pattern}"
GB_DONE_PATTERN_REMOVED = "Убрана игра: {pattern}"
GB_DONE_COMBO_ADDED = "Добавлено сочетание: {combo}"
GB_DONE_COMBO_REMOVED = "Убрано сочетание: {combo}"
GB_PATTERN_EXISTS = "Уже в списке: {pattern}"
GB_COMBO_EXISTS = "Уже в списке: {combo}"
GB_BAD_PATTERN = ("Шаблон: латиница, цифры и знаки, не больше 4 символов * и ?")
GB_BAD_COMBO = "Это не сочетание клавиш"
GB_FAILED = "Не удалось сохранить: {error}"
GB_NO_RELOAD = ("Сохранено, но Hyprland не перечитал конфиг ({error}): "
                "заработает после hyprctl reload")
GB_FULL = "Список полон"


# ---- home screen (tiles) ------------------------------------------------------

HOME_TITLE = "Главная"  # the sidebar row that leads back to the tiles
HOME_SEARCH = "Поиск по всем настройкам"
HOME_OPEN = "Открыть «{title}»"
HOME_ALL_OK = "Всё работает"
HOME_SOMETHING_DOWN = "Есть сбой"
HOME_NOW = "Сейчас: {power}"
HOME_STEPS = {"dim": "приглушить", "lock": "заблокировать", "dpms": "погасить"}
HOME_OFF = "выкл"
HOME_NOT_SET_UP = "Не настроено"
HOME_MUTED = "без звука"
HOME_NO_SOUND = "Нет устройства вывода"
HOME_WIFI_ON = "Wi-Fi: {ssid}"
HOME_WIFI_NONE = "Wi-Fi не подключён"
HOME_WIFI_OFF = "Wi-Fi выключен"
HOME_BT_ON = "Bluetooth включён"
HOME_BT_OFF = "Bluetooth выключен"
HOME_BT_DEVICES = "Bluetooth: {names}"
HOME_DEVICE = "{kind} {percent}%"
HOME_BRIGHTNESS = "Яркость {percent}%"
HOME_MODES_HINT = "Один щелчок меняет сразу несколько настроек"
HOME_THEMES_HINT = "Цвета окон, панели и меню"
HOME_THEMES_MISSING = "Программа тем не найдена"

# ---- the pages added on 15.11.2026: Monitor, Notifications, Autostart, Updates ----

PAGES.update({
    "monitor": {
        "title": "Монитор",
        "keywords": ["монитор", "экран", "дисплей", "разрешение", "масштаб", "частота",
                     "герц", "hidpi", "второй экран", "крупнее", "мельче"],
        "rows": {
            "mode": ("Разрешение и частота", ["разрешение", "частота", "герц", "hz"]),
            "scale": ("Масштаб", ["масштаб", "крупнее", "мельче", "размер", "scale"]),
            "enabled": ("Включён", ["выключить", "отключить", "второй"]),
        },
    },
    "notifications": {
        "title": "Уведомления",
        "keywords": ["уведомления", "не беспокоить", "dnd", "оповещения", "всплывающие",
                     "тишина", "hyprpanel", "notify"],
        "rows": {
            "dnd": ("Не беспокоить", ["тишина", "dnd", "не беспокоить"]),
            "notifications.position": ("Где всплывают", ["угол", "место", "позиция"]),
            "notifications.timeout": ("Сколько видно", ["время", "секунды", "таймаут"]),
            "notifications.active_monitor": ("На мониторе с фокусом", ["монитор", "экран"]),
            "notifications.showActionsOnHover": ("Кнопки только при наведении",
                                                 ["кнопки", "действия", "наведение"]),
            "notifications.ignore": ("Не показывать от программ",
                                     ["игнор", "скрыть", "программы", "заглушить"]),
            "stored": ("Сохранённые уведомления", ["очистить", "удалить", "история"]),
            "test": ("Пробное уведомление", ["проверить", "тест"]),
        },
    },
    "autostart": {
        "title": "Автозапуск",
        "keywords": ["автозапуск", "при входе", "запуск", "старт", "автозагрузка",
                     "startup", "exec"],
        "rows": {
            "own": ("Ваши программы", ["добавить", "убрать", "программы"]),
            "add.app": ("Добавить программу", ["добавить", "приложение"]),
            "add.command": ("Своя команда", ["команда", "скрипт"]),
            "system": ("Из hyprland.lua", ["конфиг", "система", "hyprland"]),
        },
    },
    "updates": {
        "title": "Обновления",
        "keywords": ["обновления", "обновить", "pacman", "yay", "пакеты", "ядро",
                     "перезагрузка", "кэш", "сироты", "pacnew"],
        "rows": {
            "pending": ("Обновления пакетов", ["ждут", "сколько", "список"]),
            "upgrade": ("Обновить систему", ["обновить", "pacman", "yay", "syu"]),
            "reboot": ("Перезагрузка", ["перезагрузить", "ядро"]),
            "last": ("Последнее полное обновление", ["когда", "дата"]),
            "cache": ("Кэш пакетов", ["кэш", "почистить", "место", "paccache"]),
            "orphans": ("Ненужные пакеты", ["сироты", "orphans", "зависимости"]),
            "pacnew": ("Файлы .pacnew", ["pacnew", "pacdiff", "настройки"]),
        },
    },
})

# Monitor
MON_GROUP = "{name} · {description}"
MON_MODE = "Разрешение и частота"
MON_MODE_VALUE = "{width}×{height}, {rate} Гц"
MON_SCALE = "Масштаб"
MON_SCALE_HINT = "Больше — крупнее текст и окна"
MON_SCALE_VALUE = "{percent} %"
MON_ENABLED = "Включён"
MON_ENABLED_HINT = "Последний включённый экран выключить нельзя"
MON_NOTE = ("Новые настройки сразу видны, и их нужно подтвердить. "
            "Сохраняются и после перезагрузки")
MON_CONFIRM = "Оставить новые настройки экрана?"
MON_CONFIRM_DETAIL = "Если не ответить, через {seconds} с всё вернётся как было."
MON_KEEP = "Оставить"
MON_REVERT = "Вернуть"
MON_REVERTED = "Вернул как было"
MON_APPLIED = "Монитор: применено"
MON_FAILED = "Монитор: не удалось — {error}"
MON_READ_FAILED = "Не удалось прочитать мониторы: {error}"
MON_NONE = "Мониторы не найдены: окно запущено не в Hyprland"
MON_NOT_LUA = "Менять монитор отсюда можно в Hyprland 0.57+ с конфигом на Lua"
MON_NOT_LOADED = ("Hyprland пока не читает настройки мониторов: "
                  "переустановите настройки (install.sh)")
MON_LABEL = "Монитор {name}"

# Notifications
NOTIF_SHOW_GROUP = "Показ"
NOTIF_DND = "Не беспокоить"
NOTIF_DND_HINT = "Уведомления копятся в панели, но не всплывают"
NOTIF_POSITION = "Где всплывают"
NOTIF_POSITION_HINT = "Угол или край экрана"
NOTIF_POSITIONS = {
    "top right": "Справа сверху", "top": "Сверху", "top left": "Слева сверху",
    "right": "Справа", "left": "Слева",
    "bottom right": "Справа снизу", "bottom": "Снизу", "bottom left": "Слева снизу",
}
NOTIF_TIMEOUT = "Сколько видно"
NOTIF_TIMEOUT_HINT = "Секунд, пока уведомление не спрячется в панель"
UNIT_S = "с"
NOTIF_ACTIVE = "На мониторе с фокусом"
NOTIF_ACTIVE_HINT = "Иначе — всегда на первом мониторе"
NOTIF_HOVER = "Кнопки только при наведении"
NOTIF_HOVER_HINT = "Кнопки действий видны, когда на уведомлении мышь"
NOTIF_IGNORE_GROUP = "Не показывать от программ"
NOTIF_IGNORE_NOTE = "Уведомления этих программ сразу закрываются: не всплывают и не сохраняются"
NOTIF_IGNORE_EMPTY = "Список пуст"
NOTIF_IGNORE_PICK = "Программа из недавних уведомлений"
NOTIF_IGNORE_NO_RECENT = "Нет недавних программ"
NOTIF_ADD = "Добавить"
NOTIF_REMOVE = "Убрать"
NOTIF_STORE_GROUP = "Сохранённые"
NOTIF_STORED = "Сохранено уведомлений: {count}"
NOTIF_STORED_UNKNOWN = "Сохранённые уведомления"
NOTIF_STORED_HINT = "Их видно в меню уведомлений панели"
NOTIF_CLEAR = "Очистить"
NOTIF_CLEAR_ASK = "Удалить все сохранённые уведомления?"
NOTIF_CLEAR_DETAIL = "Это нельзя отменить."
NOTIF_CLEARED = "Уведомления очищены"
NOTIF_TEST = "Проверить"
NOTIF_TEST_ROW = "Пробное уведомление"
NOTIF_TEST_HINT = "Показать, как уведомления выглядят сейчас"
NOTIF_TEST_SUMMARY = "Проверка уведомлений"
NOTIF_TEST_BODY = "Так уведомления выглядят сейчас"
NOTIF_NO_PANEL = "HyprPanel не отвечает, а показывает уведомления она: менять пока нечего"
NOTIF_APPLIED = "Применено: {name}"
NOTIF_FAILED = "Не удалось: {error}"
NOTIF_READ_FAILED = "Не удалось прочитать настройки уведомлений: {error}"
NOTIF_LABELS = {
    "dnd": NOTIF_DND,
    "notifications.position": NOTIF_POSITION,
    "notifications.timeout": NOTIF_TIMEOUT,
    "notifications.active_monitor": NOTIF_ACTIVE,
    "notifications.showActionsOnHover": NOTIF_HOVER,
    "notifications.ignore": NOTIF_IGNORE_GROUP,
}

# Autostart
AUTO_OWN_GROUP = "Ваши программы"
AUTO_OWN_NOTE = "Запускаются при входе в систему; добавленная сейчас — со следующего входа"
AUTO_EMPTY = "Пока пусто — добавьте программу ниже"
AUTO_ADD_GROUP = "Добавить"
AUTO_ADD_APP = "Программа"
AUTO_ADD_APP_HINT = "Из установленных"
AUTO_ADD_COMMAND = "Своя команда"
AUTO_ADD_COMMAND_HINT = "Enter или «Добавить»"
AUTO_COMMAND_PLACEHOLDER = "например, telegram-desktop -startintray"
AUTO_ADD = "Добавить"
AUTO_REMOVE = "Убрать"
AUTO_SYSTEM_GROUP = "Из hyprland.lua"
AUTO_SYSTEM_NOTE = "Эти строки меняются только в файле конфигурации; здесь они для справки"
AUTO_SYSTEM_NONE = "В hyprland.lua автозапуска нет"
AUTO_SYSTEM_UNREAD = "hyprland.lua не прочитан (нет lua5.4 или конфиг на .conf)"
AUTO_NOT_LOADED = "Hyprland пока не читает этот список: переустановите настройки (install.sh)"
AUTO_LABEL = "Автозапуск"
AUTO_SAVED = "Автозапуск: сохранено"
AUTO_FAILED = "Автозапуск: не удалось — {error}"
AUTO_DUPLICATE = "Такая команда уже есть в списке"
AUTO_IN_CONFIG = "Это уже запускается из hyprland.lua — второй раз не нужно"
AUTO_BAD = "Пустая или слишком длинная команда"
AUTO_FULL = "В списке уже {count} программ — больше нельзя"

# Updates
UPD_STATE_GROUP = "Состояние"
UPD_PENDING = "Обновления пакетов"
UPD_CHECKING = "Проверяю…"
UPD_NONE = "Система обновлена"
UPD_N = "Ждут обновления: {count}"
UPD_AUR_N = "из них из AUR: {count}"
UPD_FAILED = "Не удалось проверить: {error}"
UPD_NO_TOOL = "Нет checkupdates (пакет pacman-contrib)"
UPD_LIST_GROUP = "Что обновится"
UPD_ITEM = "{old} → {new}"
UPD_MORE = "…и ещё {count}"
UPD_UPGRADE = "Обновить систему"
UPD_UPGRADE_HINT = "Откроется терминал с «{command}»; пароль вводите там"
UPD_UPGRADE_BUTTON = "Обновить"
UPD_CHECK = "Проверить ещё раз"
UPD_CHECK_HINT = "Свежий список с зеркал, несколько секунд"
UPD_CHECK_BUTTON = "Проверить"
UPD_REBOOT = "Перезагрузка"
UPD_REBOOT_NEEDED = "Нужна: ядро обновлено, а работает старое ({running})"
UPD_REBOOT_NO = "Не нужна"
UPD_LAST = "Последнее полное обновление"
UPD_LAST_TODAY = "{date}, сегодня"
UPD_LAST_YESTERDAY = "{date}, вчера"
UPD_LAST_DAYS = "{date}, дней назад: {days}"
UPD_CLEAN_GROUP = "Уборка"
UPD_CACHE = "Кэш пакетов"
UPD_CACHE_VALUE = "{size} ГБ"
UPD_CACHE_HINT = "«Почистить» оставит по две последние версии (paccache -rk2), в терминале"
UPD_CACHE_BUTTON = "Почистить"
UPD_ORPHANS = "Ненужные пакеты"
UPD_ORPHANS_HINT = "Зависимости, которые больше ничему не нужны. Удаляйте сами, проверив список"
UPD_PACNEW = "Файлы .pacnew"
UPD_PACNEW_HINT = "Новые версии настроек после обновления; сравнить и слить — sudo pacdiff"
UPD_NOTHING = "Нет"
UPD_SOME = "{count}: {names}"
UPD_TERMINAL_OPENED = "Открыт терминал — дальше там"
UPD_TERMINAL_FAILED = "Не удалось открыть терминал: {error}"
UPD_TERMINAL_TITLE = "Обновление системы"
UPD_CACHE_TITLE = "Чистка кэша пакетов"
UPD_TERMINAL_DONE = "Готово. Enter — закрыть окно"


# ---- Appearance (fonts, icons; the cursor rows come from VARS) ------------------

LOOK_FONTS = "Шрифты"
LOOK_FONT = "Шрифт интерфейса"
LOOK_FONT_HINT = "Меню, кнопки и текст программ GTK. Программы Qt его не видят (нет qt6ct)"
LOOK_MONO = "Моноширинный шрифт"
LOOK_MONO_HINT = "Код и таблицы в программах GTK"
LOOK_SCALE = "Размер текста"
LOOK_SCALE_HINT = "Все надписи программ GTK крупнее или мельче, окна не меняются"
LOOK_PERCENT = "{percent} %"
LOOK_ELSEWHERE = "Панель и терминал"
LOOK_ELSEWHERE_NOTE = ("У панели и терминала свой шрифт. Здесь можно сделать его таким же, как "
                       "выше; значки панели при этом остаются из Nerd Font.")
LOOK_PANEL_FONT = "Шрифт панели"
LOOK_KITTY_FONT = "Шрифт терминала kitty"
LOOK_SAME_AS_UI = "Как у интерфейса"
LOOK_SAME_AS_MONO = "Как моноширинный"
LOOK_SAME_TIP = "Поставить тот же шрифт (размер останется свой)"
LOOK_NOT_FOUND = "не найден"
LOOK_MISSING = "Шрифт «{family}» не установлен: программы берут похожий"
LOOK_ICONS_GROUP = "Значки"
LOOK_ICONS = "Тема значков"
LOOK_ICONS_HINT = "Значки папок, файлов и программ"
LOOK_LABELS = {
    "look.font": "Шрифт интерфейса",
    "look.mono": "Моноширинный шрифт",
    "look.scale": "Размер текста",
    "look.icons": "Тема значков",
    "look.panel_font": "Шрифт панели",
    "look.kitty_font": "Шрифт терминала",
}
LOOK_READ_FAILED = "Не удалось прочитать оформление: {error}"
LOOK_APPLY_FAILED = "Не применилось ({name}): {error}"
LOOK_APPLIED = "Применено: {name}"
LOOK_CURSOR_RESET = "Вернуть курсор из конфига"
LOOK_CURSOR_RESET_HINT = "Только тема и размер курсора: шрифты и значки выше это не меняет"
LOOK_CURSOR_RESET_ASK = ("Тема и размер курсора снова будут из hyprland.lua. Шрифты и значки "
                         "останутся. Отменить можно через Ctrl+Z или «Историю».")
LOOK_APPLIED_NO_UNDO = "Применено: {name}. Отменить нельзя: прежнее значение не прочиталось"
LOOK_BAD_VALUE = "Такое значение нельзя сохранить"
LOOK_OWN_FONT = "Шрифт этого окна"
LOOK_OWN_FONT_HINT = ("Включено — окно Настроек пишет своим шрифтом Onest. Выключено — шрифтом "
                      "интерфейса выше. Размер текста окно слушает всегда")
LOOK_UNREADABLE = "В шрифте «{family}» нет русских или латинских букв: вместо текста квадратики"
