# T04. TENDER: навык `quantor-obmen`, образцы, адаптеры

Не Quantor: папка `/home/usrr/VSCode/Odintsov/TENDER/Работа/`. Python 3 машины (есть openpyxl, pymupdf; нет
jsonschema, numpy — без них). Формат — копия `docs/tender-exchange/01-format.md` Quantor.

## Раскладка

```text
TENDER/Работа/Quantor/
  README.md                      # что это, поток «база → расчёт → загрузка», где токен
  Базы/<NNN. Объект>/<выпуск-n>/ # распакованные базы (скачанный ZIP кладёт человек)
  Образцы/
    format.md                    # копия формата
    base/ …                      # синтетическая база: секция, оси 1–5 / А–Г, 2 квартиры + МОП, стены, стояки
    calc_heating/ …              # расчёт отопления на ней: лучи, коллектор, конвекторы, объёмы, вопрос
    calc_eom/ …                  # расчёт ЭОМ: ЩЭ, кабели до ЩК, лоток, светильники МОП, объёмы
  Скилы/quantor-obmen/
    SKILL.md
    references/{format.md, adapters.md, fit.md}
    scripts/{base_unpack.py, base_info.py, axes_fit.py, calc_pack.py, calc_validate.py, calc_push.py,
             adapt_generic.py, adapt_otoplenie_v3.py, adapt_eom_routes_v4.py}
    tests/ (pytest на образцах)
```

Ссылка `~/.claude/skills/quantor-obmen` → `Работа/Quantor/Скилы/quantor-obmen`. `Работа/CLAUDE.md` — строка в
таблице маршрутизации («Quantor, база объекта, выгрузка расчёта, токен Quantor → `Quantor/`») и раздел
«Quantor» (общий для механики и ЭОМ — исключение из «не смешивать», потому что это обмен, а не раздел);
`Работа/РЕЕСТР.md` — строка.

## Скрипты

- `base_unpack.py <zip> --object "342. ЖК Знаки (МР Групп)"` — проверка sha256 и схем, распаковка в
  `Базы/<объект>/<выпуск>/`, `base_info.md` (виды: документ, лист, этажи, корпус/секция, оси, число зон).
- `base_info.py <база> [--view <key>]` — сводка вида; `--png` — картинка вида (зоны, стены, оси) через pymupdf.
- `axes_fit.py --base <база> --view <key> --src axes.json` — аффинная привязка: вход — оси навыка (метка →
  положение в его системе: пункты листа, м от осей, мм IFC), выход — `fit_<key>.json` (матрица 2×3, оси,
  rms_mm, max_mm); общие оси по меткам; < 2+2 осей или max > 500 мм — ошибка с понятным текстом.
- `calc_pack.py --base <база> --manifest m.json --views <файлы> --quantities q.json [--questions …] --out x.zip`
  — применяет fit к точкам, округляет мм, проверяет (`calc_validate.py`), пишет sha256 в `files`.
- `calc_validate.py <zip|папка>` — все проверки формата без портала (схемы руками, запрет цен, fit, виды есть в
  базе); код выхода ≠ 0 при ошибке.
- `calc_push.py <zip> --portal URL --token-file <файл>` — `POST /api/v1/projects/{p}/tender/calcs/upload`
  с `Authorization: Bearer`; токен только из файла (по умолчанию `~/.config/quantor/token`, права 600), в
  вывод не печатать; ответ: номер версии, предупреждения. Портал — без имени пользователя в заголовках.
- Адаптеры: `adapt_otoplenie_v3.py` (вход `route_*.json` v3 объекта 342: `apts[].feed.pts`, `collector`,
  `cabinets` → polylines `T-OV-T1`, terminals/equipment, объёмы по Ø), `adapt_eom_routes_v4.py`
  (`she_routes_v4.json`, `trace_lengths_shch_v4.json` 341 → кабели `T-EOM-CAB`, щиты `equipment/panel`),
  `adapt_generic.py` (простой JSON/CSV полилиний и точек в любой системе → вид пакета). Единицы и система
  координат входа — параметром, без догадок.

## Раздел «Выгрузка в Quantor» в навыках

В `SKILL.md` каждого `raschet-*` (механика, 8 шт.) и `raschet-eom` — короткий раздел (≤ 10 строк): когда
(после приёмки расчёта человеком), какой адаптер, команда `calc_pack` → `calc_validate` → `calc_push`, цен не
выгружать, при отказе по fit — проверить оси. В `Скилы/РЕЕСТР.md` механики — строка «Связи».

Проверка: `python3 -m pytest Работа/Quantor/Скилы/quantor-obmen/tests -q`; `calc_validate.py` на обоих
образцах — 0; адаптер отопления на реальном `route_AR13_p015.json` 342 с fit по синтетике — пакет собирается.
