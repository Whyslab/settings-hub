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
        "rows": {},
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

PLACEHOLDER_TITLE = "Раздел появится на следующем шаге"
PLACEHOLDER_NOTE = "Пока здесь пусто: настройки этого раздела переносятся по одному."

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
