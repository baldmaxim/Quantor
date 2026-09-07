"""Флаги возможностей портала.

Портал показывает только то, что действительно работает. Всё остальное объявлено
выключенным, чтобы интерфейс честно показывал границу этапа, а не имитировал
функциональность.

Принцип Stage 1 сохраняется дословно: **включение флага не создаёт функциональность,
а лишь перестаёт её прятать.** Отсюда следует главное правило управления флагами:
незавершённую возможность нельзя включить из админки. Право у администратора есть,
готовности у продукта — нет, и разрешать ему пообещать пользователю несделанное значит
переложить на него ответственность за чужую недоделку.

Порядок старшинства:

    умолчание кода  <  системное переопределение  <  переопределение пространства
                    <  переменная окружения FEATURE_FLAGS

Окружение старше базы намеренно: это тот же аварийный рычаг, что и у настроек, — и
тот же способ показать возможность на демонстрации, не трогая установку.
"""

from __future__ import annotations

from dataclasses import dataclass
from types import MappingProxyType
from typing import Final


@dataclass(frozen=True, slots=True)
class FlagDefinition:
    """Описание флага. Живёт в коде: готовность — свойство продукта, а не настройки."""

    key: str
    title: str
    description: str
    default: bool
    stage: str

    # Можно ли включить из админки. У незавершённых возможностей — нет: см. преамбулу.
    admin_editable: bool = True

    # Переопределяется ли на уровне пространства. У общесистемных возможностей — нет:
    # включить просмотрщик одному арендатору и не включить другому нечем.
    workspace_scoped: bool = True

    # Значение выводится из настроенности внешней системы, а не из переопределения.
    # Включённая возможность без ключа — это обещание, которого сервер не выполнит.
    follows_configuration: bool = False


def _stage1(key: str, title: str, description: str, *, default: bool = True) -> FlagDefinition:
    return FlagDefinition(
        key=key, title=title, description=description, default=default, stage="Этап 1"
    )


def _stage2(key: str, title: str, description: str) -> FlagDefinition:
    """Возможность следующего этапа: объявлена, не реализована, из админки не включается."""
    return FlagDefinition(
        key=key,
        title=title,
        description=description,
        default=False,
        stage="Этап 2",
        admin_editable=False,
    )


REGISTRY: Final[MappingProxyType[str, FlagDefinition]] = MappingProxyType(
    {
        definition.key: definition
        for definition in (
            _stage1("projects", "Проекты", "Список проектов и карточка проекта."),
            _stage1("documents", "Документы", "Документы, ревизии и листы."),
            _stage1("uploads", "Загрузка файлов", "Приём документов и распознанных пакетов."),
            _stage1("legacy_import", "Импорт пакета", "Разбор распознанного пакета legacy-v1."),
            # Включён после сквозного прогона на эталонном пакете 2026-09-07: чертёж
            # открывается, разметка ложится на лист. До этого флаг стоял выключенным —
            # объявлять готовым то, что ни разу не открывали на настоящем документе, нельзя.
            _stage1("viewer", "Просмотрщик", "Просмотр чертежей и слой распознанных областей."),
            FlagDefinition(
                key="integrations.tenderhub",
                title="Интеграция с TenderHUB",
                description="Создание проекта из тендера. Включается наличием ключа доступа.",
                default=False,
                stage="Этап 1",
                follows_configuration=True,
            ),
            _stage2("takeoff.manual", "Ручные измерения", "Обмеры по чертежу вручную."),
            _stage2("takeoff.ai", "Автоматический подсчёт", "Распознавание элементов и объёмов."),
            _stage2("models.gateway", "Шлюз моделей", "Вызовы языковых и зрительных моделей."),
            _stage2("reports", "Отчёты", "Ведомость объёмов работ."),
            _stage2("bim.import", "Импорт BIM", "Разбор RVT, NWD, NWC и IFC."),
            _stage2("drawing.compare", "Сравнение ревизий", "Различия между версиями чертежа."),
        )
    }
)

# --- совместимость с прежней формой ---
#
# Прежние кортежи и словарь умолчаний выводятся из реестра, а не ведутся рядом: два
# списка одного и того же расходятся при первой же правке.

STAGE1_FEATURES: Final[tuple[str, ...]] = tuple(
    key for key, definition in REGISTRY.items() if definition.stage == "Этап 1"
)

STAGE2_FEATURES: Final[tuple[str, ...]] = tuple(
    key for key, definition in REGISTRY.items() if definition.stage == "Этап 2"
)

DEFAULTS: Final[MappingProxyType[str, bool]] = MappingProxyType(
    {key: definition.default for key, definition in REGISTRY.items()}
)


def parse_overrides(raw: str) -> dict[str, bool]:
    """Разбирает `takeoff.ai=true,reports=false`.

    Неизвестные имена игнорируются: опечатка в окружении не должна порождать флаг,
    которого нет в продукте.
    """
    overrides: dict[str, bool] = {}
    for chunk in raw.split(","):
        name, _, value = chunk.partition("=")
        name = name.strip()
        if name in REGISTRY:
            overrides[name] = value.strip().lower() in ("1", "true", "yes", "on")
    return overrides


def resolve(raw_overrides: str = "", *, tenderhub_configured: bool = False) -> dict[str, bool]:
    """Набор флагов без учёта базы: код плюс окружение.

    Остаётся запасным путём: `/api/v1/meta` обязан отвечать и тогда, когда таблиц
    переопределений ещё нет — на неразмеченной базе и в тестах оболочки.
    """
    resolved = {**DEFAULTS, "integrations.tenderhub": tenderhub_configured}
    return {**resolved, **parse_overrides(raw_overrides)}
