"""Карантинный каталог правил старого портала — только чтение.

Каталог собран из разбора PROMPT 00 (`legacy_build.py`) и лежит в пакете как данные. В рабочих
таблицах реестра этих правил нет: у них нет проверенных контрактов входов и выходов, а
смешивать их с правилами реестра значило бы фильтровать карантин в каждом запросе. Статус у
всех один — UNVERIFIED_LEGACY, в расчёт не идёт ни одно. Путь в реестр — только новая версия
правила с собственным типом и источником, которая ссылается на старое как на происхождение и
проходит обычное утверждение с разбором каждой известной опасности.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from dataclasses import dataclass
from functools import cache
from importlib.resources import files
from types import MappingProxyType
from typing import Any, Final

from app.contracts.calc.enums import (
    CalcLegacyAction,
    CalcLegacyCatalog,
    CalcLegacyClass,
    CalcLegacyHazard,
    CalcRuleStatus,
)
from app.contracts.calc.rules import (
    LEGACY_NOTICE,
    CalcLegacyCatalogRead,
    CalcLegacyCodeRef,
    CalcLegacyCountRead,
    CalcLegacyGroupRead,
    CalcLegacyRuleRead,
)

_PACKAGE: Final = "app.services.calc.rules"


class LegacyCatalogError(RuntimeError):
    """Каталог в пакете не совпадает со своими метаданными: число записей или отпечаток."""


def catalog_content_sha256(groups: list[dict[str, Any]], items: list[dict[str, Any]]) -> str:
    """Отпечаток записей и групп в каноническом виде — не зависит от отступов файла."""
    canonical = json.dumps(
        {"groups": groups, "items": items},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


@dataclass(frozen=True, slots=True)
class LegacyCatalog:
    catalog_version: str
    generator_version: str
    source_sha256: str
    content_sha256: str
    items: tuple[CalcLegacyRuleRead, ...]
    groups: tuple[CalcLegacyGroupRead, ...]
    by_id: MappingProxyType[str, CalcLegacyRuleRead]

    def get(self, legacy_id: str) -> CalcLegacyRuleRead | None:
        return self.by_id.get(legacy_id)


def read_packaged_text() -> str:
    """Текст каталога из ресурсов пакета — тем же путём, что и после установки колеса."""
    return files(_PACKAGE).joinpath("data", "legacy_catalog.json").read_text("utf-8")


@cache
def load_catalog() -> LegacyCatalog:
    raw = json.loads(read_packaged_text())
    if raw["entry_count"] != len(raw["items"]):
        raise LegacyCatalogError(
            f"заявлено записей {raw['entry_count']}, в каталоге {len(raw['items'])}"
        )
    if catalog_content_sha256(raw["groups"], raw["items"]) != raw["content_sha256"]:
        raise LegacyCatalogError("отпечаток записей не совпадает с заявленным")
    items = tuple(
        CalcLegacyRuleRead(
            legacy_id=item["legacy_id"],
            catalog=CalcLegacyCatalog(item["catalog"]),
            section=item["section"],
            location=item["location"],
            code_refs=[CalcLegacyCodeRef(**ref) for ref in item["code_refs"]],
            rule_text=item["rule_text"],
            class_primary=CalcLegacyClass(item["class_primary"]),
            class_secondary=[CalcLegacyClass(code) for code in item["class_secondary"]],
            class_raw=item["class_raw"],
            assumptions=item["assumptions"],
            action_raw=item["action_raw"],
            actions=[CalcLegacyAction(code) for code in item["actions"]],
            hazards=[CalcLegacyHazard(code) for code in item["hazards"]],
            group_ids=list(item["group_ids"]),
            status=CalcRuleStatus.UNVERIFIED_LEGACY,
            calculation_eligible=False,
            notice=LEGACY_NOTICE,
        )
        for item in raw["items"]
    )
    groups = tuple(
        CalcLegacyGroupRead(
            group_id=group["group_id"],
            title=group["title"],
            finding=group["finding"],
            members=list(group["members"]),
        )
        for group in raw["groups"]
    )
    by_id = MappingProxyType({item.legacy_id: item for item in items})
    return LegacyCatalog(
        catalog_version=raw["catalog_version"],
        generator_version=raw["generator_version"],
        source_sha256=raw["source_sha256"],
        content_sha256=raw["content_sha256"],
        items=items,
        groups=groups,
        by_id=by_id,
    )


def catalog_read(
    *,
    catalog: CalcLegacyCatalog | None = None,
    legacy_class: CalcLegacyClass | None = None,
    hazard: CalcLegacyHazard | None = None,
    action: CalcLegacyAction | None = None,
    group_id: str | None = None,
) -> CalcLegacyCatalogRead:
    loaded = load_catalog()
    items = [
        item
        for item in loaded.items
        if (catalog is None or item.catalog is catalog)
        and (legacy_class is None or item.class_primary is legacy_class)
        and (hazard is None or hazard in item.hazards)
        and (action is None or action in item.actions)
        and (group_id is None or group_id in item.group_ids)
    ]
    by_catalog = Counter(item.catalog.value for item in loaded.items)
    by_class = Counter(item.class_primary.value for item in loaded.items)
    return CalcLegacyCatalogRead(
        catalog_version=loaded.catalog_version,
        generator_version=loaded.generator_version,
        entry_count=len(loaded.items),
        source_sha256=loaded.source_sha256,
        content_sha256=loaded.content_sha256,
        by_catalog=[CalcLegacyCountRead(key=key, count=count) for key, count in by_catalog.items()],
        by_class=[
            CalcLegacyCountRead(key=key, count=count) for key, count in by_class.most_common()
        ],
        groups=list(loaded.groups),
        items=items,
    )
