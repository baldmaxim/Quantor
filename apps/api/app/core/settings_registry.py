"""Реестр управляемых настроек портала.

Определения живут в коде и под контролем версий; база хранит только проверенное
переопределение и его происхождение. Это принципиально: свободная таблица `key → JSON`
позволяет администратору сломать любое поведение, и починить это потом нечем.

Правило, которое держит реестр честным: **настройка добавляется вместе с местом, которое
её читает.** Определение без потребителя — это переключатель, который ничего не делает,
и обнаруживается это позже всех.

Инфраструктурные параметры сюда не переезжают: DSN базы, ключи хранилища и секрет
провайдера входа остаются в окружении (ADR-0012, ADR-0013). Тест следит, чтобы ключ
реестра не совпал с полем `Settings`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import Final

from app.auth.permissions import Permission
from app.domain import OverrideScope

SettingValue = bool | int | str | list[str]


class SettingType(StrEnum):
    BOOL = "bool"
    INTEGER = "integer"
    STRING = "string"
    ENUM = "enum"
    STRING_LIST = "string_list"


@dataclass(frozen=True, slots=True)
class SettingDefinition:
    """Описание настройки: что это, кому можно менять и в каких пределах."""

    key: str
    title: str
    description: str
    value_type: SettingType
    category: str
    default_value: SettingValue
    allowed_scopes: frozenset[OverrideScope]
    requires_permission: Permission = Permission.SETTINGS_MANAGE

    # Stage 1.5 не хранит секретов в настройках вовсе: для них отдельный канал.
    # Поле объявлено, чтобы контракт не пришлось менять, когда канал появится.
    is_secret: bool = False
    restart_required: bool = False

    minimum: int | None = None
    maximum: int | None = None
    choices: tuple[str, ...] = ()
    max_length: int | None = None

    # Верхний предел из окружения. Нужен там, где переопределение не должно позволять
    # выйти за возможности установки: администратор арендатора не может разрешить приём
    # файлов больше, чем выдержит сама инсталляция.
    deployment_ceiling_field: str | None = None

    def allows(self, scope: OverrideScope) -> bool:
        return scope in self.allowed_scopes


_SYSTEM_AND_WORKSPACE: Final[frozenset[OverrideScope]] = frozenset(
    {OverrideScope.SYSTEM, OverrideScope.WORKSPACE}
)


DEFINITIONS: Final[MappingProxyType[str, SettingDefinition]] = MappingProxyType(
    {
        definition.key: definition
        for definition in (
            SettingDefinition(
                key="uploads.max_upload_size_bytes",
                title="Предельный размер загружаемого файла",
                description=(
                    "Больше этого значения портал файл не примет. Ограничено сверху "
                    "возможностями установки: поднять выше предела окружения нельзя."
                ),
                value_type=SettingType.INTEGER,
                category="Загрузка",
                default_value=1024 * 1024 * 1024,
                allowed_scopes=_SYSTEM_AND_WORKSPACE,
                minimum=1024 * 1024,
                deployment_ceiling_field="max_upload_size_bytes",
            ),
            SettingDefinition(
                key="documents.content_url_ttl_seconds",
                title="Время жизни ссылки на файл",
                description=(
                    "Ссылка на документ действует указанное число секунд и работает в обход "
                    "портала. Чем дольше живёт, тем дольше действует у того, кто её получил."
                ),
                value_type=SettingType.INTEGER,
                category="Документы",
                default_value=3600,
                allowed_scopes=_SYSTEM_AND_WORKSPACE,
                minimum=60,
                maximum=24 * 3600,
            ),
            SettingDefinition(
                key="projects.default_sort",
                title="Порядок списка проектов по умолчанию",
                description="С чего открывается список, пока пользователь не выбрал иначе.",
                value_type=SettingType.ENUM,
                category="Проекты",
                default_value="recent",
                allowed_scopes=_SYSTEM_AND_WORKSPACE,
                choices=("recent", "name"),
            ),
        )
    }
)


@dataclass(frozen=True, slots=True)
class ResolvedSetting:
    """Действующее значение вместе с ответом на вопрос «откуда оно взялось»."""

    definition: SettingDefinition
    value: SettingValue
    source: str
    updated_by: str | None = None
    updated_at: str | None = None
    # Значения, которые лежат на нижних уровнях. Нужны интерфейсу: администратор должен
    # видеть, к чему вернётся настройка при снятии переопределения.
    inherited: dict[str, SettingValue] = field(default_factory=dict)


class SettingValueError(ValueError):
    """Значение не подходит определению. Текст безопасен для показа администратору."""


def validate(
    definition: SettingDefinition, value: object, *, ceiling: int | None = None
) -> SettingValue:
    """Приводит присланное значение к типу настройки или объясняет, почему не вышло.

    Сообщение называет нарушенное условие: «некорректное значение» не подсказывает,
    что именно исправить, и превращает настройку в угадайку.
    """
    match definition.value_type:
        case SettingType.BOOL:
            if not isinstance(value, bool):
                raise SettingValueError("ожидается true или false")
            return value

        case SettingType.INTEGER:
            # bool — подкласс int, и без этой проверки true превратится в 1.
            if isinstance(value, bool) or not isinstance(value, int):
                raise SettingValueError("ожидается целое число")
            if definition.minimum is not None and value < definition.minimum:
                raise SettingValueError(f"минимум — {definition.minimum}")
            if definition.maximum is not None and value > definition.maximum:
                raise SettingValueError(f"максимум — {definition.maximum}")
            if ceiling is not None and value > ceiling:
                raise SettingValueError(
                    f"установка не поддерживает больше {ceiling}: предел задан окружением"
                )
            return value

        case SettingType.STRING:
            if not isinstance(value, str):
                raise SettingValueError("ожидается строка")
            trimmed = value.strip()
            if definition.max_length is not None and len(trimmed) > definition.max_length:
                raise SettingValueError(f"не длиннее {definition.max_length} символов")
            return trimmed

        case SettingType.ENUM:
            if not isinstance(value, str) or value not in definition.choices:
                allowed = ", ".join(definition.choices)
                raise SettingValueError(f"допустимые значения: {allowed}")
            return value

        case SettingType.STRING_LIST:
            if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
                raise SettingValueError("ожидается список строк")
            items = [item.strip() for item in value if item.strip()]
            if definition.choices:
                unknown = sorted(set(items) - set(definition.choices))
                if unknown:
                    raise SettingValueError(f"неизвестные значения: {', '.join(unknown)}")
            # Порядок не значим, повторы бессмысленны.
            return sorted(set(items))


def get(key: str) -> SettingDefinition | None:
    return DEFINITIONS.get(key)


def all_keys() -> tuple[str, ...]:
    return tuple(DEFINITIONS)
