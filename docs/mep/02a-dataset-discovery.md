# MEP D0: агрегаты инвентаризации

Только опись, заголовки CAD и текстовый слой PDF. OCR, рендер, модели, разметка, split и alignment не выполнялись.

```json
{
  "archives_total": 22,
  "archives_status": {
    "EXTRACTED": 22
  },
  "archives_hold_reasons": {},
  "unique_files": 7264,
  "file_occurrences": 8208,
  "files_by_type": {
    ".pdf": 579,
    ".dwg": 6112,
    ".doc": 68,
    ".bak": 185,
    ".xlsx": 136,
    ".pc3": 1,
    ".calc": 6,
    ".txt": 40,
    ".dst": 53,
    ".jpg": 8,
    ".dwl": 9,
    ".dwl2": 9,
    ".err": 1,
    ".log": 6,
    ".zip": 8,
    ".docx": 27,
    ".png": 3,
    ".grd": 1,
    ".xls": 11,
    ".ds$": 1
  },
  "file_occurrences_by_type": {
    ".pdf": 613,
    ".dwg": 6653,
    ".doc": 85,
    ".bak": 395,
    ".xlsx": 218,
    ".pc3": 40,
    ".calc": 12,
    ".txt": 40,
    ".dst": 57,
    ".jpg": 10,
    ".dwl": 9,
    ".dwl2": 9,
    ".err": 1,
    ".log": 9,
    ".zip": 8,
    ".docx": 28,
    ".png": 8,
    ".grd": 1,
    ".xls": 11,
    ".ds$": 1
  },
  "pdf_pages": 28299,
  "pdf_content_kind": {
    "mixed": 14823,
    "vector": 13281,
    "raster_scan": 195
  },
  "pdf_no_text": 235,
  "scans_without_text": 195,
  "pdf_pages_with_issues": 27833,
  "pdf_page_issues": {
    "stamp_not_located": 16320,
    "image_fraction_upper_bound_custom_clipping": 24864,
    "blank_or_unclassified_page": 12,
    "image_inspection_failed:ValueError": 1,
    "text_extraction_failed:PdfStreamError": 1
  },
  "file_revision_status": {
    "current": 3136,
    "review": 2677,
    "superseded": 1451
  },
  "file_occurrence_revision_status": {
    "current": 3398,
    "review": 3003,
    "superseded": 1807
  },
  "version_sets": 4233,
  "page_revision_status": {
    "current": 9949,
    "superseded": 1318,
    "review": 17032
  },
  "fire_documents": 427,
  "pdf_files_with_errors": 15,
  "dwg_versions": {
    "AC1021": 4712,
    "AC1032": 1265,
    "AC1024": 68,
    "AC1027": 67
  },
  "dwg_with_same_path_pdf": 28,
  "projects": 1,
  "project_group_basis": {
    "cipher_prefix": 1
  },
  "pages_without_project": 1438,
  "albums_stage_discipline": {
    "P/EOM": 3,
    "P/VK": 5,
    "P/OV": 2,
    "P/unknown": 4,
    "P/SS": 3,
    "RD/unknown": 393,
    "RD/KR": 60,
    "RD/AR": 12,
    "RD/FIRE": 40,
    "RD/EOM": 20,
    "RD/OV": 14,
    "RD/VK": 14,
    "RD/SS": 9
  },
  "document_unknown_fraction": {
    "project_key": 0.034003,
    "object_code": 0.518309,
    "stage": 0.0,
    "discipline": 0.200991,
    "systems": 0.948651,
    "sheet_kind": 0.617015,
    "floor": 0.813601,
    "building": 0.314152,
    "section": 1.0,
    "pd_section": 0.99821,
    "rd_marker": 0.76473,
    "fire_system": 0.941217
  },
  "page_unknown_fraction": {
    "project_key": 0.050815,
    "object_code": 0.530902,
    "stage": 0.0,
    "discipline": 0.48666,
    "systems": 0.899714,
    "sheet_kind": 0.755716,
    "floor": 0.935404,
    "building": 0.354818,
    "section": 1.0,
    "pd_section": 0.958762,
    "rd_marker": 0.841938,
    "fire_system": 0.961094
  },
  "vk_pairs": {},
  "confirmed_floor_system_pairs": 0,
  "paired_project_sets": 0,
  "boq_or_spec_candidates": 35,
  "poc_targets": {
    "projects": [20, 30],
    "paired_sets": [40, 60],
    "floor_system_pairs": [150, 300]
  },
  "pilot_candidates": 0,
  "unconfirmed_candidates": 10,
  "section_unknown_reasons": {
    "no_evidence": 28299
  },
  "manual_sample_sizes": {
    "5.2": 50,
    "5.3": 50
  }
}
```

## Ограничения и вопросы владельцу

- Project ID подтверждается шифром или явно подписанным именем объекта; общая папка не доказывает принадлежность к проекту. Число групп может отличаться от числа строительных объектов.
- Альбомом в агрегатах считается уникальный PDF. Совпадение имени DWG/PDF в одной исходной папке — кандидат, не подтверждение одинакового содержания.
- AUTO_OK требует также совпадения корпуса и секции; неизвестные значения дают REVIEW. Связь П→РД по различным корпусам 1:N получает REVIEW; неоднозначность внутри корпуса — HOLD.
- Цели PoC: 20–30 проектов, 40–60 парных комплектов, 150–300 пар этаж–система. Подтверждённые пары считаются нижней оценкой; REVIEW и HOLD в неё не входят.
- Формат страницы и доля изображения получены из PDF-операторов, не из визуальной оценки. Пользовательские clip paths отмечаются как верхняя оценка. Штамп — кандидат в нижнем правом углу с характерными подписями; читаемость человеком не проверялась.
- Имена ZIP без флага UTF-8 требуют выбранной кодировки; исходные байты сохранены. 7-Zip возвращает Unicode, исходные байты имён недоступны и отмечены null.
- Для XLS имена листов недоступны без дополнительного парсера; содержимое таблиц не читалось.
- Выбрать лист, систему и этаж из частного pilot_candidates.json для PROMPT 02. При нехватке кандидатов дополнить комплект, не подменять неизвестные поля догадками.
- Если PDF недостаточно, решить отдельно вопрос конвертера DWG и ezdxf через лицензионный гейт.
- Штампы сканов без текстового слоя остаются недоступны: нужен отдельный дальнейший шаг.
- Нужны ли кандидаты ВОР сейчас или только к PROMPT 10?

STOP после D0.

## D0.1 limitations

Project grouping now uses the drawing-code prefix; buildings do not define projects. The old project_key rule required an explicit Project/Object label. Section remains unknown when no explicit section label exists in the extracted text or paths; a building is not a section.

Revision selection uses revision number, then date, within the same project/building/stage/discipline and normalized filename. Equal-ranked different payloads require review. Different sheet names are not assumed to be versions of the same set. Superseded payloads remain stored and counted in total inventory, but are excluded from pairs and pilots.

Issue counts overlap: custom clipping means image area is an upper bound; stamp_not_located does not mean the PDF is unreadable. Extraction/inspection failures and blank pages are separate.

Manual samples contain up to 50 randomly selected pages per requested PD section, with a fixed seed. They contain candidate title lines and stamp text only; null stamps remain null. Unconfirmed pilot candidates require manual verification and do not change observed classifications.

R-MEP-3 additional objects: owner decision pending. STOP after D0.1.

## Validation

pnpm test:vision: PASS, 216 tests in the working tree (including 4 separate D1 coordinate tests). Ruff and mypy PASS. pnpm lint:licenses: PASS, 0 violations. No OCR, raster rendering, models or new libraries were used for D0.1. Source/output SHA-256 verification is recorded in verification.json. The source archives and superseded payloads are retained.

Conflicting project-prefix evidence is excluded from project grouping; an object-code fallback cannot override that conflict. Section has no explicit evidence in the inspected stamp/title/path sources; it is not inferred from a building.
