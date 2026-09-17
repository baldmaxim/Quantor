"""Versioned conservative rules. Examples are executed by synthetic parametrized tests."""

from __future__ import annotations

import re
from dataclasses import dataclass

from .common import FIELDS, Evidence, Finding

RULES_VERSION = "1.1.0"


@dataclass(frozen=True)
class Rule:
    rule_id: str
    field: str
    pattern: str
    value: str | None
    example: str
    expected: str
    sources: tuple[str, ...] = ()


RULES = (
    Rule(
        "project.object_prefix",
        "project_key",
        r"^(\d{2,4}[А-ЯA-Z]{2,4})(?=[-.]|$)",
        None,
        "42АБ",
        "42АБ",
        ("object_code",),
    ),
    Rule(
        "pd.section",
        "pd_section",
        r"(?<!\d)(5\.[1-5])(?!\d)",
        None,
        "Раздел 5.2",
        "5.2",
        ("pd_section",),
    ),
    Rule(
        "rd.marker",
        "rd_marker",
        r"(?:^|[-_/ ])(ВК[12]?|К|АПТ|ППТ)(?=$|[-_. /])",
        None,
        "42АБ-РД-ВК1.pdf",
        "ВК1",
        ("rd_marker",),
    ),
    Rule(
        "fire.marker",
        "fire_system",
        r"(?:^|[-_/ ])(?:АПТ|ППТ)(?=$|[-_. /\d])",
        "yes",
        "42АБ-РД-АПТ.pdf",
        "yes",
        ("rd_marker",),
    ),
    Rule("stage.archive_p", "stage", r"(?:^|/)PD(?=/|$)", "P", "PD/file", "P", ("directory",)),
    Rule("stage.archive_rd", "stage", r"(?:^|/)RD(?=/|$)", "RD", "RD/file", "RD", ("directory",)),
    Rule("stage.cipher_rd", "stage", r"-РД-", "RD", "42АБ-К1-РД-ВК", "RD"),
    Rule(
        "project.cipher_prefix",
        "project_key",
        r"\b(\d{2,4}[А-ЯA-Z]{2,4})(?=-)",
        None,
        "42АБ-К1-РД-ВК",
        "42АБ",
    ),
    Rule(
        "building.cipher",
        "building",
        r"\b\d{2,4}[А-ЯA-Z]{2,4}-(К[1-7]|ПА)(?=[-.])",
        None,
        "42АБ-К1-РД-ВК",
        "К1",
    ),
    Rule(
        "disc.pd_51",
        "discipline",
        r"(?<!\d)5\.1(?!\d)",
        "EOM",
        "Раздел 5.1",
        "EOM",
        ("pd_section",),
    ),
    Rule(
        "disc.pd_52", "discipline", r"(?<!\d)5\.2(?!\d)", "VK", "Раздел 5.2", "VK", ("pd_section",)
    ),
    Rule(
        "disc.pd_53", "discipline", r"(?<!\d)5\.3(?!\d)", "VK", "Раздел 5.3", "VK", ("pd_section",)
    ),
    Rule(
        "disc.pd_54", "discipline", r"(?<!\d)5\.4(?!\d)", "OV", "Раздел 5.4", "OV", ("pd_section",)
    ),
    Rule(
        "disc.pd_55", "discipline", r"(?<!\d)5\.5(?!\d)", "SS", "Раздел 5.5", "SS", ("pd_section",)
    ),
    Rule(
        "disc.rd_k",
        "discipline",
        r"(?:^|[-_/ ])К(?=$|[-_. /])",
        "VK",
        "42АБ-РД-К.pdf",
        "VK",
        ("rd_marker",),
    ),
    Rule(
        "disc.rd_fire",
        "discipline",
        r"(?:^|[-_/ ])(?:АПТ|ППТ)(?=$|[-_. /\d])",
        "FIRE",
        "42АБ-РД-АПТ.pdf",
        "FIRE",
        ("rd_marker",),
    ),
    Rule(
        "sheet.basement",
        "sheet_kind",
        r"\bплан\s+подвала\b",
        "floor_plan",
        "План подвала",
        "floor_plan",
    ),
    Rule(
        "sheet.typical",
        "sheet_kind",
        r"\bтиповой\s+(?:жилой\s+)?этаж\b",
        "floor_plan",
        "Типовой этаж",
        "floor_plan",
    ),
    Rule("floor.basement", "floor", r"\bплан\s+подвала\b", "подвал", "План подвала", "подвал"),
    Rule(
        "disc.water_title",
        "discipline",
        r"\bводоснабжени[ея]\b",
        "VK",
        "Система водоснабжения",
        "VK",
    ),
    Rule("disc.sewer_title", "discipline", r"\bканализаци[яию]\b", "VK", "Канализация", "VK"),
    Rule("disc.heat_title", "discipline", r"\bотоплени[ея]\b", "OV", "Отопление", "OV"),
    Rule("stage.p", "stage", r"(?:^|[\s/!_\-])(ПД|PD|П)(?=$|[\s/!_\-.])", "P", "PD/file", "P"),
    Rule("stage.rd", "stage", r"(?:^|[\s/!_\-])(РД|RD)(?=$|[\s/!_\-.])", "RD", "RD/file", "RD"),
    Rule(
        "stage.work",
        "stage",
        r"\b(?:стадия\s*[:\-]?\s*Р|рабочая документация)\b",
        "RD",
        "Стадия Р",
        "RD",
    ),
    Rule(
        "stage.design", "stage", r"\bпроектная документация\b", "P", "Проектная документация", "P"
    ),
    Rule(
        "disc.vk",
        "discipline",
        r"(?:^|[\s/!_\-.])(ВК|VK)(?=$|[\s/!_\-.\d])",
        "VK",
        "X-ВК1.pdf",
        "VK",
    ),
    Rule(
        "disc.water",
        "discipline",
        r"водоснабжени[ея].{0,30}канализаци[яию]",
        "VK",
        "Водоснабжение и канализация",
        "VK",
    ),
    Rule(
        "disc.ov", "discipline", r"(?:^|[\s/!_\-.])(ОВ|OV)(?=$|[\s/!_\-.\d])", "OV", "ОВ.pdf", "OV"
    ),
    Rule(
        "disc.eom",
        "discipline",
        r"(?:^|[\s/!_\-.])(ЭОМ|ЭО|ЭМ)(?=$|[\s/!_\-.\d])",
        "EOM",
        "ЭОМ.pdf",
        "EOM",
    ),
    Rule(
        "disc.ss", "discipline", r"(?:^|[\s/!_\-.])(СС|SS)(?=$|[\s/!_\-.\d])", "SS", "СС.pdf", "SS"
    ),
    Rule(
        "disc.ar", "discipline", r"(?:^|[\s/!_\-.])(АР|AR)(?=$|[\s/!_\-.\d])", "AR", "АР.pdf", "AR"
    ),
    Rule(
        "disc.kr",
        "discipline",
        r"(?:^|[\s/!_\-.])(КР|КЖ|КМ)(?=$|[\s/!_\-.\d])",
        "KR",
        "КЖ.pdf",
        "KR",
    ),
    Rule(
        "system.code", "systems", r"(?<![\w])([ВТК][1-4])(?:\.[0-9]+)?(?!\w)", None, "В1 К1", "В1"
    ),
    Rule(
        "sheet.plan",
        "sheet_kind",
        r"\bплан(?:ы)?\b.{0,90}(?:этаж|отм\.)",
        "floor_plan",
        "План 3 этажа",
        "floor_plan",
    ),
    Rule("sheet.axon", "sheet_kind", r"аксонометр", "axonometry", "Аксонометрия В1", "axonometry"),
    Rule(
        "sheet.scheme",
        "sheet_kind",
        r"(?<!аксонометрическая )\bсхем[аы]\b",
        "scheme",
        "Схема В1",
        "scheme",
    ),
    Rule(
        "sheet.spec",
        "sheet_kind",
        r"спецификаци[яию]",
        "specification",
        "Спецификация",
        "specification",
    ),
    Rule(
        "sheet.general",
        "sheet_kind",
        r"общие\s+данные",
        "general_data",
        "Общие данные",
        "general_data",
    ),
    Rule("sheet.detail", "sheet_kind", r"\b(?:узел|деталь|узлы)\b", "detail", "Узел 1", "detail"),
    Rule(
        "floor.number",
        "floor",
        r"(?<![\d,\-])\b(\d{1,2})\s*(?:-?(?:го|й|ый))?\s*этаж",
        None,
        "План 3 этажа",
        "3",
    ),
    Rule("floor.prefix", "floor", r"\bэтаж\s*[:№]?\s*(\d{1,2})\b", None, "Этаж 4", "4"),
    Rule(
        "floor.typical",
        "floor",
        r"типов(?:ой|ого|ые|ых)\s+(?:жил(?:ой|ого|ые|ых)\s+)?этаж",
        "типовой",
        "Типовой жилой этаж",
        "типовой",
    ),
    Rule(
        "floor.elevation",
        "floor",
        r"\bотм\.?\s*([+\-]?\d{1,3}[.,]\d{3})",
        None,
        "План на отм. +3.000",
        "+3.000",
    ),
    Rule(
        "building",
        "building",
        r"\bкорпус\s*[:№]?\s*([\d]+(?:[.\-][\d]+)?[А-ЯA-Z]?)\b",
        None,
        "Корпус 2",
        "2",
    ),
    Rule("section", "section", r"\bсекци[яи]\s*[:№]?\s*([\d]+[А-ЯA-Z]?)\b", None, "Секция 3", "3"),
    Rule(
        "project.explicit",
        "project_key",
        r"(?:проект|объект)\s*[:=]\s*([^\n;]{3,100})",
        None,
        "Объект: SYNTHETIC",
        "SYNTHETIC",
    ),
    Rule(
        "object.explicit",
        "object_code",
        r"(?:шифр объекта|код объекта|object_code)\s*[:=]\s*([\w.\-/]+)",
        None,
        "Код объекта: SYN-001",
        "SYN-001",
    ),
    Rule(
        "object.drawing",
        "object_code",
        r"\b([A-ZА-Я0-9][A-ZА-Я0-9.]{1,15}(?:-[A-ZА-Я0-9.]{1,15}){0,3})-(?:П|РД|Р)-(?:ВК|ОВ|АР|ЭОМ|КЖ|КР)(?:\b|\d)",
        None,
        "SYN-001-П-ВК",
        "SYN-001",
    ),
)

# These are also versioned parsing rules, separate from classification fields.
TITLE_PATTERN = r"план|схем|аксонометр|общие\s+данные|спецификаци|\bузел\b|\bдеталь\b"
STAMP_LABEL_PATTERN = r"стадия|листов|кол\.?\s*уч|шифр|разраб|проверил"
BOQ_PATTERN = r"\bвор\b|ведомост.*объ[её]м|спецификац|\bboq\b|\bspec\b"
DXF_VERSION_PATTERN = rb"\$ACADVER\s+1\s+(AC\d{4})"


def normalize(value: str) -> str:
    return " ".join(value.upper().replace("Ё", "Е").split()).replace(",", ".")


def classify(sources: list[tuple[str, str]]) -> dict[str, Finding]:
    found: dict[str, list[Evidence]] = {name: [] for name in FIELDS}
    for source, text in sources:
        for line in text.splitlines():
            for rule in RULES:
                if rule.sources and source not in rule.sources:
                    continue
                if rule.rule_id == "system.code" and source in (
                    "directory",
                    "filename",
                    "rd_marker",
                    "pd_section",
                ):
                    continue
                for match in re.finditer(rule.pattern, line, re.IGNORECASE):
                    if rule.rule_id == "system.code" and any(
                        m.start() <= match.start() < m.end()
                        for m in re.finditer(
                            r"\b\d{2,4}[А-ЯA-Z]{2,4}-К[1-7](?=[-.])", line, re.IGNORECASE
                        )
                    ):
                        continue
                    value = rule.value if rule.value is not None else normalize(match.group(1))
                    found[rule.field].append(Evidence(source, line, rule.rule_id, value))
    prefix_rule = next(r for r in RULES if r.rule_id == "project.object_prefix")
    for item in found["object_code"]:
        prefix_match = re.search(prefix_rule.pattern, item.value, re.IGNORECASE)
        if prefix_match:
            found["project_key"].append(
                Evidence(
                    item.source, item.line, prefix_rule.rule_id, normalize(prefix_match.group(1))
                )
            )
    result = {}
    for name, evidence in found.items():
        chosen = evidence
        if name == "stage":
            explicit = [
                e
                for e in evidence
                if e.rule
                in (
                    "stage.archive_p",
                    "stage.archive_rd",
                    "stage.cipher_rd",
                    "stage.work",
                    "stage.design",
                )
            ]
            if explicit:
                chosen = explicit
        if name == "discipline":
            mapped = [
                e
                for e in evidence
                if e.rule.startswith("disc.pd_") or e.rule in ("disc.rd_fire", "disc.rd_k")
            ]
            if mapped:
                chosen = mapped
        if name == "project_key":
            prefixes = [
                e for e in evidence if e.rule in ("project.cipher_prefix", "project.object_prefix")
            ]
            if prefixes:
                chosen = prefixes
        if name == "building":
            for e in evidence:
                if e.rule == "building" and re.fullmatch(r"[1-7]", e.value):
                    e.value = "К" + e.value
        values = {item.value for item in chosen}
        if name == "systems":
            # Multiple systems on one page are valid; source disagreement is not.
            by_source: dict[str, set[str]] = {}
            for item in evidence:
                by_source.setdefault(item.source, set()).add(item.value)
            conflict = len({tuple(sorted(v)) for v in by_source.values()}) > 1
            value = ",".join(sorted(values)) if values and not conflict else "unknown"
        else:
            conflict = len(values) > 1
            value = next(iter(values)) if len(values) == 1 else "unknown"
        reason = "conflicting_evidence" if conflict else ("no_evidence" if not values else None)
        result[name] = Finding(value, evidence, reason)
    return result


def path_sources(paths: list[str]) -> list[tuple[str, str]]:
    sources: list[tuple[str, str]] = []
    for path in paths:
        normalized = path.replace("\\", "/").replace("!", "/")
        directory, _, filename = normalized.rpartition("/")
        sources.extend((("filename", filename), ("directory", directory)))
        if re.search(r"(?:^|/)PD(?:/|$)", normalized, re.IGNORECASE):
            sources.append(("pd_section", normalized))
        if re.search(r"(?:^|/)RD(?:/|$)|-РД-", normalized, re.IGNORECASE):
            sources.append(("rd_marker", normalized))
    return sources
