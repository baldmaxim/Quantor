"""Перечисления расчётного контура (ADR-0030).

Каждое перечисление носит префикс `Calc`: у MEP-эксперимента около семидесяти
неквалифицированных имён схем (`ReviewStatus`, `SourceType`…), и одноимённый класс
заставил бы FastAPI переименовать обе схемы — а с ними и типы фронтенда MEP.

Значения — заглавными, как в пакете промтов: по ним их узнаёт инженер, читающий отчёт.
"""

from __future__ import annotations

from enum import StrEnum


class CalcFactMethod(StrEnum):
    """Как получено значение факта."""

    DOCUMENT_EXPLICIT = "DOCUMENT_EXPLICIT"
    """Прямо написано в документе: пояснительная записка, ТУ, задание."""
    TABLE_EXPLICIT = "TABLE_EXPLICIT"
    """Прямо написано в таблице: квартирография, экспликация, таблица нагрузок."""
    TABLE_COUNTED = "TABLE_COUNTED"
    """Подсчитано по явно перечисленным строкам таблицы: квартиры экспликации этажа, кухни.

    Не расчёт и не вывод: число строк, каждая из которых — свидетельство. Отдельный метод, а
    не TABLE_EXPLICIT, потому что самого числа в ячейке нет, и проверяющий должен это видеть.
    """
    GEOMETRY_MEASURED = "GEOMETRY_MEASURED"
    """Измерено по чертежу с калибровкой (ручной обмер)."""
    CALCULATED = "CALCULATED"
    """Вычислено расчётным ядром."""
    INFERRED = "INFERRED"
    """Выведено зарегистрированным детерминированным правилом. Выход модели сюда не попадает."""
    NORMATIVE = "NORMATIVE"
    """Из нормативного правила реестра."""
    MANUFACTURER_RULE = "MANUFACTURER_RULE"
    """Из правила производителя."""
    ASSUMPTION = "ASSUMPTION"
    """Инженерное допущение с явным основанием."""
    MANUAL = "MANUAL"
    """Ручной ввод инженера."""


class CalcSourceClass(StrEnum):
    """Класс источника. От него зависит приоритет, но не «глобальная истина»."""

    ARCHITECTURE = "ARCHITECTURE"
    """АР: планы, разрезы, генплан."""
    APARTMENT_SCHEDULE = "APARTMENT_SCHEDULE"
    """Квартирография."""
    ROOM_SCHEDULE = "ROOM_SCHEDULE"
    """Экспликация помещений."""
    MEP_DESIGN = "MEP_DESIGN"
    """Инженерные разделы стадии П: ВК, ОВ, ЭОМ."""
    CONSUMER_TABLE = "CONSUMER_TABLE"
    """Таблицы потребителей и нагрузок."""
    AIR_EXCHANGE_TABLE = "AIR_EXCHANGE_TABLE"
    """Таблицы воздухообменов."""
    FIXTURE_TABLE = "FIXTURE_TABLE"
    """Таблицы санитарных приборов и водопотребления."""
    EXPLANATORY_NOTE = "EXPLANATORY_NOTE"
    """Текстовые пояснительные записки."""
    TECHNICAL_CONDITIONS = "TECHNICAL_CONDITIONS"
    """Технические условия."""
    ADJACENT_TASK = "ADJACENT_TASK"
    """Задания смежных разделов."""
    BRAND_LIST = "BRAND_LIST"
    """Бренд-листы."""
    TECHNICAL_REQUIREMENTS = "TECHNICAL_REQUIREMENTS"
    """Технические требования Заказчика."""
    CUSTOMER_VOR = "CUSTOMER_VOR"
    """ВОР Заказчика. Объект сверки, а не эталон: в снимок для ядра не входит никогда."""
    MANUAL = "MANUAL"
    """Ручной ввод и решения инженера."""


class CalcDocumentStage(StrEnum):
    """Заявленная стадия документа. Задаётся при заведении источника, в ревизию не пишется."""

    P = "P"
    RD = "RD"
    UNKNOWN = "UNKNOWN"


class CalcDiscipline(StrEnum):
    """Раздел проекта, к которому относится инженерная система."""

    VK = "VK"
    OV = "OV"
    EOM = "EOM"
    SS = "SS"
    APT = "APT"


class CalcConfidence(StrEnum):
    """Уверенность в значении. Категория, а не число: дробь из ручного ввода декоративна."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class CalcReviewStatus(StrEnum):
    """Проверка человеком."""

    UNREVIEWED = "UNREVIEWED"
    CONFIRMED = "CONFIRMED"
    REJECTED = "REJECTED"


class CalcFactStatus(StrEnum):
    """Жизненный цикл утверждения. Значение не меняется никогда — меняется только статус."""

    ACTIVE = "ACTIVE"
    SUPERSEDED = "SUPERSEDED"
    """Тот же источник позже сообщил новое значение."""
    WITHDRAWN = "WITHDRAWN"
    """Отозвано с причиной. Не удаляется: по нему мог быть посчитан результат."""


class CalcValueKind(StrEnum):
    """Вид значения факта."""

    NUMBER = "NUMBER"
    COUNT = "COUNT"
    BOOLEAN = "BOOLEAN"
    ENUM = "ENUM"
    TEXT = "TEXT"
    RANGE = "RANGE"


class CalcEvidenceKind(StrEnum):
    """Вид свидетельства.

    Ячейки файлов xlsx и обмеры появятся вместе со своими адаптерами и своими колонками.
    """

    MANUAL_ENTRY = "MANUAL_ENTRY"
    """Ручной ввод: автор, время, основание."""
    DOCUMENT_FRAGMENT = "DOCUMENT_FRAGMENT"
    """Место в документе проекта: ревизия, страница или лист, область, фрагмент текста."""
    ASSUMPTION_BASIS = "ASSUMPTION_BASIS"
    """Основание допущения и рассмотренные альтернативы."""
    REGION_TABLE = "REGION_TABLE"
    """Строки или ячейка таблицы в тексте блока распознанного пакета."""
    REGION_TEXT = "REGION_TEXT"
    """Фрагмент текста блока распознанного пакета."""


class CalcConflictStatus(StrEnum):
    """Состояние конфликта ключа факта."""

    OPEN = "OPEN"
    """Источники расходятся, решения нет."""
    RESOLVED = "RESOLVED"
    """Есть решение человека, и набор утверждений с тех пор не менялся."""
    REOPENED = "REOPENED"
    """Решение есть, но набор утверждений изменился — его надо пересмотреть."""
    OBSOLETE = "OBSOLETE"
    """Расхождения больше нет: утверждение отозвано, заменено или отклонено."""


class CalcResolutionState(StrEnum):
    """Как получено действующее значение ключа. Ни одно состояние не выбирает молча."""

    MISSING = "MISSING"
    """Нет ни одного утверждения, допущенного к расчёту."""
    SINGLE = "SINGLE"
    """Одно утверждение."""
    CORROBORATED = "CORROBORATED"
    """Несколько утверждений согласны в пределах допуска."""
    DECIDED = "DECIDED"
    """Расхождение решено человеком."""
    DECIDED_STALE = "DECIDED_STALE"
    """Решение человека действует, но после него появились новые утверждения."""
    AUTO_PREFERRED = "AUTO_PREFERRED"
    """Расхождение, значение взято по политике приоритета; конфликт остаётся открытым."""
    UNRESOLVED = "UNRESOLVED"
    """Расхождение без решения: значения нет."""


class CalcPolicyMode(StrEnum):
    """Режим политики приоритета для типа факта."""

    MANUAL_REQUIRED = "MANUAL_REQUIRED"
    AUTO_PREFER = "AUTO_PREFER"


# ------------------------------------------------------------ сбор исходных данных (PROMPT 02)


class CalcTableKind(StrEnum):
    """Смысл распознанной таблицы — по заголовкам и названию, а не по имени файла."""

    APARTMENT_EXPLICATION = "APARTMENT_EXPLICATION"
    """Экспликация квартир этажа: секции, квартиры, помещения квартир."""
    ROOM_EXPLICATION = "ROOM_EXPLICATION"
    """Экспликация помещений: МОП, коммерция, технические помещения."""
    PARKING_STORAGE = "PARKING_STORAGE"
    """Экспликация машиномест и кладовых: помещений с водой в ней не перечисляют."""
    APARTMENT_SUMMARY = "APARTMENT_SUMMARY"
    """Квартирография: сводка квартир по типам или этажам."""
    SANITARY_FIXTURES = "SANITARY_FIXTURES"
    """Санитарные приборы."""
    WATER_CONSUMERS = "WATER_CONSUMERS"
    """Потребители и расходы воды."""
    LOADS = "LOADS"
    """Нагрузки: электрические, тепловые."""
    AIR_EXCHANGE = "AIR_EXCHANGE"
    """Воздухообмены и характеристики систем вентиляции."""
    EQUIPMENT_SPEC = "EQUIPMENT_SPEC"
    """Спецификация оборудования, изделий и материалов (форма ГОСТ 21.110)."""
    UNKNOWN = "UNKNOWN"
    """Смысл не определён — таблица не используется."""


class CalcInspectionIssueCode(StrEnum):
    """Почему кандидат не стал утверждением или что осталось непроверенным. Видно пользователю."""

    UNSCOPED = "UNSCOPED"
    """Значение найдено, но не привязано к месту: не понятно, какой этаж или корпус."""
    UNIT_MISSING = "UNIT_MISSING"
    """Число без единицы, и правила, задающего единицу, нет."""
    UNIT_MISMATCH = "UNIT_MISMATCH"
    """Единица не подходит типу факта."""
    VALUE_INVALID = "VALUE_INVALID"
    """Значение не подходит типу факта."""
    APPROXIMATE = "APPROXIMATE"
    """Приблизительное значение («≈», «около»): в реестр только вручную, с основанием."""
    SELF_CONTRADICTION = "SELF_CONTRADICTION"
    """Документ сообщает разные значения одного факта — выбирать молча нельзя."""
    SCOPE_MISMATCH = "SCOPE_MISMATCH"
    """Место в документе расходится с заявленным: например, другой корпус."""
    TABLE_NOT_EXTRACTED = "TABLE_NOT_EXTRACTED"
    """Таблица распознана по смыслу, но извлечение из неё ещё не реализовано."""
    ROW_NOT_UNDERSTOOD = "ROW_NOT_UNDERSTOOD"
    """Строку таблицы не удалось разобрать."""
    UNMAPPED_LABEL = "UNMAPPED_LABEL"
    """Подпись не сопоставлена с перечнем: например, тип квартиры «2Е»."""
    VOR_QUANTITY_IGNORED = "VOR_QUANTITY_IGNORED"
    """Количество из ВОР Заказчика не принято: ВОР не вход расчёта."""
    VOR_DIAMETER_IGNORED = "VOR_DIAMETER_IGNORED"
    """Диаметр или типоразмер из ВОР Заказчика не принят: ВОР не определяет решения расчёта."""
    VOR_NOT_ADMISSIBLE = "VOR_NOT_ADMISSIBLE"
    """Факт этого типа из ВОР Заказчика не хранится вовсе."""
    DISCIPLINE_MISSING = "DISCIPLINE_MISSING"
    """Обозначение системы найдено, но раздел документа не заявлен: «В1» не отличить от вытяжки."""


class CalcRequirementLevel(StrEnum):
    """Насколько исходное данное нужно расчёту. Не уверенность — другое понятие."""

    REQUIRED = "REQUIRED"
    """Без него расчёт системы не выполняется."""
    DESIRABLE = "DESIRABLE"
    """Без него расчёт идёт на допущениях, и это видно в результате."""
    OPTIONAL = "OPTIONAL"
    """Уточняет расчёт или служит для сверки."""
    DERIVABLE = "DERIVABLE"
    """Отдельно не вводится: выводится из других фактов правилом расчёта."""


class CalcAssumptionPolicy(StrEnum):
    """Можно ли временно заменить отсутствующее значение допущением."""

    NOT_ALLOWED = "NOT_ALLOWED"
    """Только факт из документа или ручной ввод по документу."""
    MANUAL = "MANUAL"
    """Допущение инженера с основанием и альтернативами."""
    REGISTERED_RULE = "REGISTERED_RULE"
    """Значение по зарегистрированному правилу (реестр правил — PROMPT 03)."""


class CalcRequirementGroup(StrEnum):
    """Группа исходных данных в каталоге требований."""

    GEOMETRY = "GEOMETRY"
    """Геометрия объекта."""
    APARTMENTS = "APARTMENTS"
    """Квартирография."""
    NONRESIDENTIAL = "NONRESIDENTIAL"
    """Нежилые помещения."""
    WATER_SUPPLY = "WATER_SUPPLY"
    """Водоснабжение."""
    SEWERAGE = "SEWERAGE"
    """Канализация."""
    OTHER = "OTHER"
    """ТУ, требования Заказчика, производители."""


class CalcRequirementScope(StrEnum):
    """К чему относится требование: к корпусу, этажу или системе."""

    BUILDING = "BUILDING"
    FLOOR = "FLOOR"
    SYSTEM = "SYSTEM"


class CalcReadinessStatus(StrEnum):
    """Состояние исходного данного в матрице готовности. MISSING — не ноль."""

    FOUND = "FOUND"
    """Есть действующее значение без открытого расхождения."""
    CONFLICTED = "CONFLICTED"
    """Источники расходятся, расхождение не решено."""
    DERIVABLE = "DERIVABLE"
    """Прямого значения нет, но есть всё, из чего его выведет расчёт."""
    MANUAL_REQUIRED = "MANUAL_REQUIRED"
    """Автоматически не извлекается или нужного документа нет — нужен ручной ввод."""
    NOT_INSPECTED = "NOT_INSPECTED"
    """Есть распознанные документы, которые ещё не проверялись на этот факт."""
    UNKNOWN = "UNKNOWN"
    """Определить сейчас нельзя: значение не привязано к месту, таблица не разобрана."""
    MISSING = "MISSING"
    """Все распознанные документы проверены — значения нет."""


class CalcFactUsage(StrEnum):
    """Идёт ли утверждение в расчёт — отвечает сервер, интерфейс не вычисляет."""

    USED = "USED"
    """Это значение пойдёт в расчёт."""
    AGREES = "AGREES"
    """Согласно с выбранным значением."""
    NOT_CHOSEN = "NOT_CHOSEN"
    """Выбрано другое значение: решением человека или политикой приоритета."""
    CONFLICT = "CONFLICT"
    """Расхождение не решено — в расчёт не идёт ни одно значение ключа."""
    EXCLUDED_VOR = "EXCLUDED_VOR"
    """ВОР Заказчика — только для сверки."""
    REJECTED = "REJECTED"
    """Отклонено при проверке."""


class CalcStageBasis(StrEnum):
    """Откуда известна стадия документа."""

    DECLARED = "DECLARED"
    """Заявлена пользователем и совпадает со штампом или штампа нет."""
    DECLARED_OVER_STAMP = "DECLARED_OVER_STAMP"
    """Заявлена пользователем вопреки штампу — расхождение записано в сводке."""


# -------------------------------------------------------------------- реестр правил (PROMPT 03)


class CalcRuleType(StrEnum):
    """Тип правила. Тип не повышает статус: эвристика не становится нормой от смены типа."""

    PHYSICS = "PHYSICS"
    """Физическая или математическая зависимость."""
    GEOMETRY = "GEOMETRY"
    """Геометрическое правило."""
    NORMATIVE = "NORMATIVE"
    """По нормативному документу: только с документом, редакцией и пунктом."""
    MANUFACTURER = "MANUFACTURER"
    """Правило конкретного производителя и линейки — к другим не применяется."""
    ENGINEERING = "ENGINEERING"
    """Воспроизводимая инженерная методика с основанием и областью применения."""
    TENDER_ASSUMPTION = "TENDER_ASSUMPTION"
    """Явное тендерное допущение стадии П: не норматив и не факт документации."""


class CalcRuleStatus(StrEnum):
    """Жизненный цикл версии правила. В расчёт идёт только APPROVED — это вычисляется."""

    DRAFT = "DRAFT"
    """Черновик: редактируется, в расчёт не идёт."""
    UNVERIFIED_LEGACY = "UNVERIFIED_LEGACY"
    """Правило старого портала в карантинном каталоге: не проверено и не используется в расчёте."""
    APPROVED = "APPROVED"
    """Утверждено инженером; содержание неизменно."""
    DEPRECATED = "DEPRECATED"
    """Устарело: для нового расчёта не выбирается, для воспроизведения старого доступно."""
    REJECTED = "REJECTED"
    """Отклонено при проверке."""


class CalcRuleSourceKind(StrEnum):
    """Вид источника правила. ВОР Заказчика источником правила не бывает."""

    NORMATIVE_DOCUMENT = "NORMATIVE_DOCUMENT"
    MANUFACTURER_DOCUMENT = "MANUFACTURER_DOCUMENT"
    ENGINEERING_METHOD = "ENGINEERING_METHOD"
    OWNER_DECISION = "OWNER_DECISION"
    REVIEWER_DECISION = "REVIEWER_DECISION"
    LEGACY_CODE = "LEGACY_CODE"
    """Код старого портала — происхождение, но не основание для утверждения."""
    OTHER = "OTHER"


class CalcRuleInputKind(StrEnum):
    """Откуда правило берёт вход."""

    FACT = "FACT"
    """Факт реестра фактов по типу: снимок подготовит расчётное ядро."""
    QUANTITY = "QUANTITY"
    """Величина, которую выдаёт другой шаг расчёта; связывание — PROMPT 04."""


class CalcLegacyCatalog(StrEnum):
    """Каталог разбора старого портала (PROMPT 00)."""

    VK = "VK"
    K = "K"
    OV = "OV"
    VRF = "VRF"
    FIRE = "FIRE"


class CalcLegacyClass(StrEnum):
    """Класс правила старого портала по разбору PROMPT 00."""

    PHYSICS = "PHYSICS"
    NORMATIVE = "NORMATIVE"
    MANUFACTURER = "MANUFACTURER"
    GEOMETRY = "GEOMETRY"
    HEURISTIC = "HEURISTIC"
    TENDER = "TENDER"
    UNKNOWN_ORIGIN = "UNKNOWN_ORIGIN"
    ERROR = "ERROR"
    NONE = "NONE"
    """Строка каталога без правила: заглушка интерфейса."""


class CalcLegacyAction(StrEnum):
    """Предложенное аудитом действие."""

    KEEP_AS_LEGACY = "KEEP_AS_LEGACY"
    """UL: только объявленный резерв с предупреждением."""
    REPLACE = "REPLACE"
    """ЗАМЕНА: нормативным или физическим методом после проверки инженером."""
    MAKE_INPUT = "MAKE_INPUT"
    """ВВОД: сделать явным входом."""
    REJECT = "REJECT"
    """ОТКАЗ: не переносить."""
    OUT_OF_SCOPE = "OUT_OF_SCOPE"
    """Вне контура: цены, НДС, импорт счетов."""
    IDEA = "IDEA"
    """Идея для нового контура: правило не переносится, переносится подход."""


class CalcLegacyHazard(StrEnum):
    """Известная опасность правила старого портала — её нельзя утвердить молча."""

    DOUBLE_MULTIPLICATION = "DOUBLE_MULTIPLICATION"
    CONFLICTING_CONSTANTS = "CONFLICTING_CONSTANTS"
    HIDDEN_DEFAULT = "HIDDEN_DEFAULT"
    SUBSTITUTED_VALUES = "SUBSTITUTED_VALUES"
    UNIT_ERROR = "UNIT_ERROR"
    DEFECT = "DEFECT"
    """Класс «ошибочное» в разборе."""


class CalcHazardOutcome(StrEnum):
    """Итог разбора одной известной опасности правила старого портала."""

    CONFIRMED_SAFE = "CONFIRMED_SAFE"
    """Проверено: в новой версии опасность не проявляется."""
    FIXED = "FIXED"
    """Опасность была и устранена в новой версии."""
    NOT_APPLICABLE = "NOT_APPLICABLE"
    """Часть старого правила, к которой относится опасность, в новую версию не взята."""
    REJECTED = "REJECTED"
    """Опасность подтверждена и не устранена: версию утверждать нельзя."""
