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
        "rows": {},
    },
    "animations": {
        "title": "Анимации",
        "keywords": ["анимация", "пресет", "распад", "скорость", "движение", "эффекты"],
        "rows": {},
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
