"""Сборка карантинного каталога правил старого портала из разбора PROMPT 00.

Источник — человекочитаемые каталоги `docs/calc/legacy/*.md` и сквозные находки
`data/legacy_findings.json`. Результат — `data/legacy_catalog.json`: машиночитаемый карантин,
который читают реестр правил и API. Каталог не правится руками: тест собирает его заново из
разбора и сверяет побайтно, поэтому ни одна строка не теряется и не меняется молча.

Сборка детерминирована: порядок строк — порядок каталогов и строк разбора, ключи и отступы
фиксированы, путей локальной машины в результате нет. Метаданные — версия каталога и
генератора, число записей, отпечаток входов (`source_sha256`) и отпечаток самих записей
(`content_sha256`), который загрузчик сверяет при чтении из пакета.

    python -m app.services.calc.rules.legacy_build

Каждая строка сохраняет дословное место в старом коде, текст правила, класс и действие из
разбора. Разобранные ссылки на файл, строки и функцию — удобство; истина — дословный текст.
Признаки опасности выделяются по явным словам разбора и дополняются находками; пустой список
признаков не доказывает, что правило безопасно.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any, Final

from app.contracts.calc.enums import (
    CalcLegacyAction,
    CalcLegacyCatalog,
    CalcLegacyClass,
    CalcLegacyHazard,
)
from app.core.config import REPO_ROOT
from app.services.calc.rules.legacy import catalog_content_sha256

CATALOG_VERSION: Final = "calc.legacy_catalog.v1"
GENERATOR_VERSION: Final = "calc.legacy_build.v1"
DOCS: Final = REPO_ROOT / "docs" / "calc" / "legacy"
DATA: Final = Path(__file__).with_name("data")

FILES: Final[dict[CalcLegacyCatalog, str]] = {
    CalcLegacyCatalog.VK: "vk.md",
    CalcLegacyCatalog.K: "k.md",
    CalcLegacyCatalog.OV: "ov.md",
    CalcLegacyCatalog.VRF: "vrf.md",
    CalcLegacyCatalog.FIRE: "fire.md",
}
# Файл старого кода, к которому относятся номера строк без имени файла.
MAIN_FILES: Final[dict[CalcLegacyCatalog, str | None]] = {
    CalcLegacyCatalog.VK: None,
    CalcLegacyCatalog.K: "public/sewage-calculator.html",
    CalcLegacyCatalog.OV: "public/ventilation-calculator.html",
    CalcLegacyCatalog.VRF: "public/air-conditioning.html",
    CalcLegacyCatalog.FIRE: "public/fire-protection.html",
}
ABBREVIATIONS: Final[dict[str, str]] = {
    "cF": "collectFittings",
    "cFB": "collectFittingsForBuilding",
}

CLASS_CODES: Final[dict[str, CalcLegacyClass]] = {
    "физ": CalcLegacyClass.PHYSICS,
    "норм": CalcLegacyClass.NORMATIVE,
    "произв": CalcLegacyClass.MANUFACTURER,
    "марка": CalcLegacyClass.MANUFACTURER,
    "марки": CalcLegacyClass.MANUFACTURER,
    "геом": CalcLegacyClass.GEOMETRY,
    "эвр": CalcLegacyClass.HEURISTIC,
    "тенд": CalcLegacyClass.TENDER,
    "неизв": CalcLegacyClass.UNKNOWN_ORIGIN,
    "ошиб": CalcLegacyClass.ERROR,
    "—": CalcLegacyClass.NONE,
}
ACTION_WORDS: Final[tuple[tuple[re.Pattern[str], CalcLegacyAction], ...]] = (
    (re.compile(r"\bUL\b"), CalcLegacyAction.KEEP_AS_LEGACY),
    (re.compile(r"ЗАМЕНА"), CalcLegacyAction.REPLACE),
    (re.compile(r"ВВОД"), CalcLegacyAction.MAKE_INPUT),
    (re.compile(r"ОТКАЗ"), CalcLegacyAction.REJECT),
    (re.compile(r"вне контура", re.IGNORECASE), CalcLegacyAction.OUT_OF_SCOPE),
    (re.compile(r"новая разработка|выбрать одно", re.IGNORECASE), CalcLegacyAction.REPLACE),
    (re.compile(r"\bидея\b", re.IGNORECASE), CalcLegacyAction.IDEA),
)
# «см. 002», «как 026» — действие той же строки каталога, на которую ссылается разбор.
_ACTION_REFERENCE = re.compile(r"^(?:см\.|как)\s+(\d{3})\b")
# Явные слова разбора. Признак — повод для ручной проверки, а не диагноз.
HAZARD_WORDS: Final[tuple[tuple[re.Pattern[str], CalcLegacyHazard], ...]] = (
    (
        re.compile(r"дважды|двойн\w*\s+(сч[её]т|умнож)|квадратичн", re.IGNORECASE),
        CalcLegacyHazard.DOUBLE_MULTIPLICATION,
    ),
    (
        re.compile(r"умолчани|молча\b|молчалив|жёстко|зашит", re.IGNORECASE),
        CalcLegacyHazard.HIDDEN_DEFAULT,
    ),
    (
        re.compile(r"подставля|подстав\w+\s+молча|чуж\w+\s+квартирограф", re.IGNORECASE),
        CalcLegacyHazard.SUBSTITUTED_VALUES,
    ),
    (
        re.compile(
            r"компл\.\s*[»\"]?\s*×\s*м|усл\.\s*ед|периметр\s+как|метры\s+в\s+поле|"
            r"вместо\s+наружного|размерност",
            re.IGNORECASE,
        ),
        CalcLegacyHazard.UNIT_ERROR,
    ),
    (
        re.compile(r"противоречит|в другой таблице|против\s+\d", re.IGNORECASE),
        CalcLegacyHazard.CONFLICTING_CONSTANTS,
    ),
)

_SPLIT = re.compile(r"(?<!\\)\|")
_FILE_REF = re.compile(r"([A-Za-z0-9_\-]+\.(?:js|html))(?::\s*([0-9][0-9 ,\-–]*[0-9]))?")
_SYMBOL = re.compile(r"`([A-Za-z_][A-Za-z0-9_]*)`")
_LINES = re.compile(r"\d+(?:\s*[-–]\s*\d+)?")


def _cells(line: str) -> list[str]:
    body = line.strip()
    body = body[1:] if body.startswith("|") else body
    body = body[:-1] if body.endswith("|") else body
    return [cell.strip().replace("\\|", "|") for cell in _SPLIT.split(body)]


def _classes(raw: str) -> tuple[CalcLegacyClass, list[CalcLegacyClass]]:
    head, _, rest = raw.partition("(")
    primary = CLASS_CODES.get(head.strip())
    if primary is None:
        raise ValueError(f"неизвестный класс «{raw}»")
    secondary: list[CalcLegacyClass] = []
    for token in re.split(r"[,;]", rest.split("—")[0].rstrip(")")):
        code = CLASS_CODES.get(token.strip())
        if code is not None and code not in secondary and code is not primary:
            secondary.append(code)
    return primary, secondary


def _actions(raw: str) -> list[CalcLegacyAction]:
    found = [
        (match.start(), action)
        for pattern, action in ACTION_WORDS
        for match in pattern.finditer(raw)
    ]
    ordered: list[CalcLegacyAction] = []
    for _, action in sorted(found, key=lambda item: item[0]):
        if action not in ordered:
            ordered.append(action)
    return ordered


def _code_refs(catalog: CalcLegacyCatalog, location: str) -> list[dict[str, str | None]]:
    refs: list[dict[str, str | None]] = []
    symbols = _SYMBOL.findall(location)
    for match in _FILE_REF.finditer(location):
        refs.append({"file": match.group(1), "lines": match.group(2), "symbol": None})
    main = MAIN_FILES[catalog]
    if not refs and main is not None:
        lines = ", ".join(_LINES.findall(location)) or None
        abbreviations = [ABBREVIATIONS[word] for word in re.findall(r"\bcFB?\b", location)]
        symbol = (symbols or abbreviations or [None])[0]
        refs.append({"file": main, "lines": lines, "symbol": symbol})
    elif refs and symbols:
        refs[0]["symbol"] = symbols[0]
    return refs


def _rows(catalog: CalcLegacyCatalog, text: str) -> Iterator[dict[str, Any]]:
    section = ""
    for line in text.splitlines():
        if line.startswith("### ") or line.startswith("## "):
            section = line.lstrip("#").strip()
        if not line.startswith("| LEG-"):
            continue
        cells = _cells(line)
        if len(cells) != 6:
            raise ValueError(f"в строке {cells[0]} не шесть столбцов")
        legacy_id, location, rule, class_raw, assumptions, action_raw = cells
        primary, secondary = _classes(class_raw)
        yield {
            "legacy_id": legacy_id,
            "catalog": catalog.value,
            "section": section,
            "location": location,
            "code_refs": _code_refs(catalog, location),
            "rule_text": rule,
            "class_primary": primary.value,
            "class_secondary": [item.value for item in secondary],
            "class_raw": class_raw,
            "assumptions": assumptions,
            "action_raw": action_raw,
            "actions": [item.value for item in _actions(action_raw)],
        }


def build(docs: Path = DOCS, findings_path: Path = DATA / "legacy_findings.json") -> dict[str, Any]:
    digest = hashlib.sha256()
    items: list[dict[str, Any]] = []
    for catalog, name in FILES.items():
        text = (docs / name).read_text(encoding="utf-8")
        digest.update(name.encode() + b"\0" + text.encode("utf-8") + b"\0")
        items.extend(_rows(catalog, text))
    # Текстом, а не байтами: перевод строк рабочей копии не меняет отпечаток входов.
    findings_text = findings_path.read_text(encoding="utf-8")
    findings = json.loads(findings_text)
    digest.update(findings_text.encode("utf-8"))

    ids = [item["legacy_id"] for item in items]
    if len(set(ids)) != len(ids):
        raise ValueError("идентификаторы каталога повторяются")
    known = set(ids)
    groups: dict[str, list[str]] = {}
    for group in findings["groups"]:
        missing = set(group["members"]) - known
        if missing or len(group["members"]) < 2:
            raise ValueError(f"группа {group['group_id']}: неизвестные или одиночные члены")
        for member in group["members"]:
            groups.setdefault(member, []).append(group["group_id"])
    curated: dict[str, set[str]] = {}
    for hazard, members in findings["hazards"].items():
        CalcLegacyHazard(hazard)
        for member in members:
            if member not in known:
                raise ValueError(f"находка {hazard}: неизвестное правило {member}")
            curated.setdefault(member, set()).add(hazard)

    by_id = {item["legacy_id"]: item for item in items}
    for item in items:
        reference = _ACTION_REFERENCE.match(item["action_raw"])
        if not item["actions"] and reference:
            prefix = item["legacy_id"].rsplit("-", 1)[0]
            target = by_id.get(f"{prefix}-{reference.group(1)}")
            if target is None:
                raise ValueError(f"{item['legacy_id']}: ссылка на неизвестную строку")
            item["actions"] = list(target["actions"])

    for item in items:
        text = f"{item['rule_text']} {item['assumptions']}"
        hazards = {hazard.value for pattern, hazard in HAZARD_WORDS if pattern.search(text)}
        hazards |= curated.get(item["legacy_id"], set())
        if item["legacy_id"] in groups:
            hazards.add(CalcLegacyHazard.CONFLICTING_CONSTANTS.value)
        if CalcLegacyClass.ERROR.value in (item["class_primary"], *item["class_secondary"]):
            hazards.add(CalcLegacyHazard.DEFECT.value)
        item["hazards"] = sorted(hazards)
        item["group_ids"] = groups.get(item["legacy_id"], [])

    return {
        "catalog_version": CATALOG_VERSION,
        "generator_version": GENERATOR_VERSION,
        "entry_count": len(items),
        "source_sha256": digest.hexdigest(),
        "content_sha256": catalog_content_sha256(findings["groups"], items),
        "groups": findings["groups"],
        "items": items,
    }


def render(catalog: dict[str, Any]) -> str:
    return json.dumps(catalog, ensure_ascii=False, indent=1) + "\n"


def main() -> None:
    target = DATA / "legacy_catalog.json"
    target.write_text(render(build()), encoding="utf-8")
    print(f"Каталог старых правил -> {target}")


if __name__ == "__main__":
    main()
