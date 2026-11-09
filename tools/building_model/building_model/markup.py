"""Разметка для человека: модель и PNG-наложение каждого листа-плана и один статический index.html.

Страница строится только стандартной библиотекой, без внешних файлов, скриптов и сети: таблица
листов
(страница, этажи, масштаб и способ, вердикт, число стен и проёмов, блокеры), ссылка на PNG, легенда
и готовая команда подтверждения листа. Подтверждает человек (команда `approve`), не эта команда.
"""

from __future__ import annotations

import html
import shlex
from dataclasses import dataclass
from pathlib import Path

from building_model.approval import NOISE_BLOCKER
from building_model.canonical import BuildingModel
from building_model.overlay import LEGEND
from building_model.pipeline import TenderArgs, build_model, dumps_model
from building_model.reader import Document, Excluded, SheetIn, load_document, read_sheet

MM_PER_INCH = 25.4
PT_PER_INCH = 72.0
APPROVE_PLACEHOLDER = "ФИО подтверждающего"
NOISE_NOTE = "шумный лист: сначала проверьте"


@dataclass(frozen=True)
class SheetRow:
    page: int
    floors: list[int]
    ratio: int | None
    scale_method: str
    scale_confident: bool
    verdict: str
    walls: int
    openings: int
    openings_no_host: int
    blockers: int
    warnings: int
    model_file: str
    image: str | None
    note: str | None
    approve_command: str
    # Шумный лист (блокер openings_noise): подтверждение только с флагом --accept-noise.
    noisy: bool = False


@dataclass(frozen=True)
class MarkupResult:
    rows: list[SheetRow]
    excluded: dict[str, int]
    models_built: int
    models_reused: int
    images: int


def scale_ratio(mm_per_pt: float | None) -> int | None:
    """N из масштаба 1:N по мм здания на pt бумаги."""
    if mm_per_pt is None or mm_per_pt <= 0:
        return None
    return round(mm_per_pt * PT_PER_INCH / MM_PER_INCH)


def approve_command(
    input_path: Path, model_path: Path, approval_path: Path, page: int, accept_noise: bool = False
) -> str:
    parts = [
        "python -m building_model approve",
        f"--input {shlex.quote(str(input_path))}",
        f"--model {shlex.quote(str(model_path))}",
        f"--page {page}",
        f'--by "{APPROVE_PLACEHOLDER}"',
        f"--out {shlex.quote(str(approval_path))}",
    ]
    if accept_noise:
        parts.append("--accept-noise")
    return " ".join(parts)


def _load_or_build(doc: Document, page: int, path: Path) -> tuple[BuildingModel, bool]:
    """Готовая модель листа из out-dir, иначе построить и записать. Второе значение — построена."""
    if path.is_file():
        return BuildingModel.model_validate_json(path.read_text(encoding="utf-8")), False
    model = build_model(doc, page, TenderArgs())
    path.write_text(dumps_model(model), encoding="utf-8")
    return model, True


def _render_image(input_path: Path, model_path: Path, sheet: SheetIn, pdf: Path, png: Path) -> str:
    """Строит PNG; возвращает пустую строку при успехе, иначе короткую причину (без путей)."""
    if sheet.scale.mm_per_pt is None:
        return "картинка не построена: у листа нет масштаба"
    from building_model.overlay import render_overlay

    try:
        render_overlay(input_path, model_path, sheet.page, pdf, png)
    except ImportError:
        return "картинка не построена: нет pypdfium2 или Pillow (окружение .venv-reader)"
    except Exception as exc:
        # Текст исключения может содержать путь к PDF: сообщаем только вид.
        return f"картинка не построена: {type(exc).__name__}"
    return ""


def _pages_to_mark(doc: Document, pages: list[int] | None) -> list[int]:
    if pages is None:
        return doc.pages()
    missing = [p for p in pages if p not in doc.sheets]
    if missing:
        raise ValueError(f"в комплекте нет страниц: {', '.join(str(p) for p in missing)}")
    return sorted(pages)


def run_markup(
    input_path: Path, pdf: Path | None, out_dir: Path, pages: list[int] | None = None
) -> MarkupResult:
    doc = load_document(input_path)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows: list[SheetRow] = []
    excluded: dict[str, int] = {}
    built = reused = images = 0
    for page in _pages_to_mark(doc, pages):
        sheet = read_sheet(doc, page)
        if isinstance(sheet, Excluded):
            excluded[sheet.reason] = excluded.get(sheet.reason, 0) + 1
            continue
        model_path = out_dir / f"model_{page}.json"
        model, was_built = _load_or_build(doc, page, model_path)
        noisy = any(i.code == NOISE_BLOCKER and i.severity == "blocker" for i in model.review.items)
        built += int(was_built)
        reused += int(not was_built)
        image: str | None = None
        note: str | None = None
        if pdf is not None:
            png = out_dir / f"overlay_{page}.png"
            failure = _render_image(input_path, model_path, sheet, pdf, png)
            if failure:
                note = failure
            else:
                image = png.name
                images += 1
        rows.append(
            SheetRow(
                page=page,
                floors=sorted(sheet.title.floors) if sheet.title is not None else [],
                ratio=scale_ratio(sheet.scale.mm_per_pt),
                scale_method=sheet.scale.method,
                scale_confident=sheet.scale.confident,
                verdict=sheet.verdict,
                walls=len(model.walls),
                openings=len(model.openings),
                openings_no_host=sum(1 for o in model.openings if o.host is None),
                blockers=model.review.blockers,
                warnings=model.review.warnings,
                model_file=model_path.name,
                image=image,
                note=note,
                approve_command=approve_command(
                    input_path, model_path, out_dir / f"approval_{page}.json", page, noisy
                ),
                noisy=noisy,
            )
        )
    return MarkupResult(rows, dict(sorted(excluded.items())), built, reused, images)


_CSS = """
:root{color-scheme:light dark;--bg:#fafafa;--surface:#fff;--text:#1b1f24;--muted:#5b6570;
--border:#d0d7de;--accent:#0b57d0;--danger:#b3261e}
@media (prefers-color-scheme:dark){:root{--bg:#14171a;--surface:#1c2025;--text:#e6e9ec;
--muted:#9aa5b1;--border:#343b43;--accent:#8ab4f8;--danger:#f2b8b5}}
*{box-sizing:border-box}
body{margin:0;padding:max(12px,env(safe-area-inset-top)) max(12px,env(safe-area-inset-right))
max(12px,env(safe-area-inset-bottom)) max(12px,env(safe-area-inset-left));background:var(--bg);
color:var(--text);font:16px/1.45 system-ui,sans-serif;-webkit-tap-highlight-color:transparent}
h1{font-size:1.25rem;margin:0 0 .5rem}h2{font-size:1.05rem;margin:1.25rem 0 .5rem}
p,li{overflow-wrap:anywhere}.muted{color:var(--muted)}
.scroll{overflow:auto;overscroll-behavior:contain;border:1px solid var(--border);
border-radius:8px;background:var(--surface)}
table{border-collapse:collapse;width:100%;min-width:760px}
th,td{padding:.5rem .6rem;border-bottom:1px solid var(--border);text-align:left;vertical-align:top}
th{font-weight:600;white-space:nowrap}td.num{text-align:right;font-variant-numeric:tabular-nums}
.bad{color:var(--danger);font-weight:600}
a{color:var(--accent);display:inline-block;min-height:44px;line-height:44px;
touch-action:manipulation}
summary{cursor:pointer;min-height:44px;line-height:44px;color:var(--accent)}
pre{margin:0 0 .5rem;white-space:pre-wrap;overflow-wrap:anywhere;font-size:.85rem}
.legend{list-style:none;padding:0;margin:0}.legend li{display:flex;gap:.6rem;align-items:center;
padding:.25rem 0}
.sw{flex:none;width:28px;height:12px;border-radius:3px;border:1px solid var(--border)}
{SWATCHES}
@media (prefers-reduced-motion:reduce){*{transition:none!important;animation:none!important}}
"""


def _e(value: object) -> str:
    return html.escape(str(value), quote=True)


def _scale_cell(row: SheetRow) -> str:
    ratio = "нет" if row.ratio is None else f"1:{row.ratio}"
    mark = "" if row.scale_confident else " (не подтверждён самим plangeom)"
    return f"{_e(ratio)}, {_e(row.scale_method)}{_e(mark)}"


def _row_html(row: SheetRow) -> str:
    floors = ", ".join(str(f) for f in row.floors) or "не указаны"
    if row.image is not None:
        picture = f'<a href="{_e(row.image)}">PNG</a>'
    else:
        picture = _e(row.note or "без PDF картинки нет")
    noise_note = f'<p class="bad">{_e(NOISE_NOTE)}</p>' if row.noisy else ""
    blockers_class = ' class="num bad"' if row.blockers else ' class="num"'
    return (
        "<tr>"
        f'<td class="num">{row.page}</td><td>{_e(floors)}</td><td>{_scale_cell(row)}</td>'
        f"<td>{_e(row.verdict)}</td>"
        f'<td class="num">{row.walls}</td><td class="num">{row.openings}</td>'
        f'<td class="num">{row.openings_no_host}</td>'
        f"<td{blockers_class}>{row.blockers}</td>"
        f'<td class="num">{row.warnings}</td>'
        f"<td>{picture}</td>"
        f"<td>{noise_note}<details><summary>Команда</summary>"
        f"<pre>{_e(row.approve_command)}</pre></details></td>"
        "</tr>"
    )


def _swatch_css() -> str:
    return "".join(
        f".sw{i}{{background:rgb({r},{g},{b})}}" for i, (_, (r, g, b), _) in enumerate(LEGEND)
    )


def render_index(result: MarkupResult, title: str = "Разметка листов") -> str:
    """Статическая страница. Все строки из данных проходят через html.escape."""
    head = (
        "<th>Страница</th><th>Этажи</th><th>Масштаб и способ</th><th>Вердикт plangeom</th>"
        "<th>Стен</th><th>Проёмов</th><th>Без хозяина</th><th>Блокеров</th>"
        "<th>Предупреждений</th><th>Разметка</th><th>Подтверждение</th>"
    )
    body = "".join(_row_html(r) for r in result.rows)
    legend = "".join(
        f'<li><span class="sw sw{i}"></span><span><b>{_e(name)}</b>: {_e(text)}</span></li>'
        for i, (name, _, text) in enumerate(LEGEND)
    )
    skipped = ", ".join(f"{_e(reason)}: {n}" for reason, n in result.excluded.items())
    skipped_html = (
        f'<p class="muted">Не планы и отбракованные листы: {skipped}.</p>' if skipped else ""
    )
    css = _CSS.replace("{SWATCHES}", _swatch_css())
    return (
        '<!doctype html>\n<html lang="ru"><head><meta charset="utf-8">'
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">'
        '<meta name="color-scheme" content="light dark">'
        f"<title>{_e(title)}</title><style>{css}</style></head><body>"
        f"<h1>{_e(title)}</h1>"
        '<p class="muted">Модели и масштаб — кандидаты. Масштаб и модель листа подтверждает '
        "человек: скопируйте команду листа, подставьте имя и выполните из каталога "
        "tools/building_model. Пакет для Revit без подтверждения не строится.</p>"
        '<div class="scroll"><table>'
        f"<thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>"
        f"{skipped_html}"
        f'<h2>Легенда наложения</h2><ul class="legend">{legend}</ul>'
        "</body></html>\n"
    )


def write_index(result: MarkupResult, out_dir: Path) -> Path:
    path = out_dir / "index.html"
    path.write_text(render_index(result), encoding="utf-8")
    return path
