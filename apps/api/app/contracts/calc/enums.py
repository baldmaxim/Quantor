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

    Ячейки таблиц распознанного пакета, ячейки файлов и обмеры появятся вместе с
    адаптерами источников (PROMPT 02) — вместе со своими колонками.
    """

    MANUAL_ENTRY = "MANUAL_ENTRY"
    """Ручной ввод: автор, время, основание."""
    DOCUMENT_FRAGMENT = "DOCUMENT_FRAGMENT"
    """Место в документе проекта: ревизия, страница или лист, область, фрагмент текста."""
    ASSUMPTION_BASIS = "ASSUMPTION_BASIS"
    """Основание допущения и рассмотренные альтернативы."""


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
