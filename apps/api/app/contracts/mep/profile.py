"""Профиль системы: единственное место, где появляется специфика дисциплины.

Ядро знает только общие виды evidence (символ, трасса, зона, текст) и топологические роли узлов
(источник, потребитель, разветвление…). Конкретные классы, атрибуты, типы связей и системы — ВК,
ОВ или любая другая — описываются профилем с версией и источником и в код ядра не попадают.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal

from pydantic import Field, model_validator

from app.contracts.mep.common import (
    CONTRACT_VERSION,
    ContractModel,
    GeometryKind,
    Identifier,
    ProfileKey,
)


class EvidenceKind(StrEnum):
    """Что можно увидеть на листе — без дисциплины."""

    SYMBOL = "symbol"
    ROUTE = "route"
    ZONE = "zone"
    TEXT = "text"


class NodeRole(StrEnum):
    """Топологическая роль узла сети. Роль — не класс: класс задаёт профиль."""

    SOURCE = "source"
    TERMINAL = "terminal"
    JUNCTION = "junction"
    EQUIPMENT = "equipment"
    DEVICE = "device"
    TRANSITION = "transition"
    ENDPOINT = "endpoint"
    UNRESOLVED_ANCHOR = "unresolved_anchor"


class ProfileStatus(StrEnum):
    SYNTHETIC = "synthetic"
    DRAFT = "draft"
    APPROVED = "approved"


class ValueType(StrEnum):
    STRING = "string"
    NUMBER = "number"
    INTEGER = "integer"
    BOOLEAN = "boolean"


class AttributeDef(ContractModel):
    key: ProfileKey
    value_type: ValueType
    unit: str | None = None
    allowed_values: tuple[str, ...] = ()


class ClassDef(ContractModel):
    """Класс элемента. Слой evidence и слой сети описываются раздельно даже для одного объекта."""

    key: ProfileKey
    label: Annotated[str, Field(min_length=1, max_length=128)]
    layer: Literal["evidence", "network"]
    evidence_kind: EvidenceKind | None = None
    network_element: Literal["node", "segment"] | None = None
    node_roles: tuple[NodeRole, ...] = ()
    allowed_geometry: tuple[GeometryKind, ...] = ()
    attribute_keys: tuple[ProfileKey, ...] = ()
    # Как класс попадает в ВОР: длина участка, штуки узла или никак. Решает профиль, не ядро.
    quantity: Literal["length", "count", "none"] = "none"
    # Параметры, без которых строка ВОР не определена (размер, материал…). Не выводятся.
    quantity_group_keys: tuple[ProfileKey, ...] = ()

    @model_validator(mode="after")
    def _quantity_is_consistent(self) -> ClassDef:
        expected = {"segment": "length", "node": "count"}.get(self.network_element or "")
        if self.quantity != "none" and self.quantity != expected:
            raise ValueError("длина — только у участка, штуки — только у узла")
        if not set(self.quantity_group_keys) <= set(self.attribute_keys):
            raise ValueError("ключи группировки ВОР входят в attribute_keys класса")
        if self.quantity == "none" and self.quantity_group_keys:
            raise ValueError("ключи группировки без правила количества не нужны")
        return self

    @model_validator(mode="after")
    def _layer_is_consistent(self) -> ClassDef:
        if self.layer == "evidence":
            if self.evidence_kind is None or self.network_element is not None or self.node_roles:
                raise ValueError("класс evidence задаёт evidence_kind и не задаёт элемент сети")
            if not self.allowed_geometry:
                raise ValueError("класс evidence перечисляет допустимую геометрию")
        else:
            if self.network_element is None or self.evidence_kind is not None:
                raise ValueError("класс сети задаёт network_element и не задаёт evidence_kind")
            if (self.network_element == "node") != bool(self.node_roles):
                raise ValueError("роли перечисляются только у класса узла, и у него обязательно")
        return self


class RelationTypeDef(ContractModel):
    key: ProfileKey
    label: Annotated[str, Field(min_length=1, max_length=128)]
    from_kinds: tuple[EvidenceKind, ...]
    to_kinds: tuple[EvidenceKind, ...]


class SystemDef(ContractModel):
    """Система. `tree` запрещает циклы в сети этой системы — правило профиля, а не ядра."""

    key: ProfileKey
    label: Annotated[str, Field(min_length=1, max_length=128)]
    topology: Literal["tree", "any"] = "any"


class MepSystemProfile(ContractModel):
    schema_version: Literal["0.3.0"] = CONTRACT_VERSION
    profile_id: Identifier
    profile_version: Annotated[str, Field(min_length=1, max_length=32)]
    discipline: Annotated[str, Field(min_length=1, max_length=64)]
    title: Annotated[str, Field(min_length=1, max_length=256)]
    status: ProfileStatus
    # Кто и по каким листам утвердил профиль. Классы «на глаз» не принимаются.
    source: Annotated[str, Field(min_length=1, max_length=1024)]
    systems: tuple[SystemDef, ...]
    classes: tuple[ClassDef, ...]
    attributes: tuple[AttributeDef, ...] = ()
    relation_types: tuple[RelationTypeDef, ...] = ()

    def class_def(self, key: str) -> ClassDef | None:
        return next((item for item in self.classes if item.key == key), None)

    def attribute_def(self, key: str) -> AttributeDef | None:
        return next((item for item in self.attributes if item.key == key), None)

    def relation_def(self, key: str) -> RelationTypeDef | None:
        return next((item for item in self.relation_types if item.key == key), None)

    def system_def(self, key: str) -> SystemDef | None:
        return next((item for item in self.systems if item.key == key), None)
