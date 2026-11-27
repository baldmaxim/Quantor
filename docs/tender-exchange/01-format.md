# Формат обмена Quantor ↔ TENDER, версия 1

Решение — [ADR-0051](../adr/0051-quantor-kak-repozitorij-tendernyh-raschyotov.md). Образцы — `samples/` рядом,
схемы проверки — `schemas/`. Все JSON — UTF-8 без BOM, числа — JSON-числа, координаты — **целые мм**.

## Два пакета

| Пакет | Направление | Кто создаёт | Схема |
|---|---|---|---|
| База объекта | Quantor → TENDER | координатор кнопкой «Выпустить базу», дальше ZIP скачивается и кладётся в `TENDER/Работа/Quantor/Базы/` вручную | `quantor.object_base.v1` |
| Расчёт | TENDER → Quantor | навык `quantor-obmen` (`calc_push.py`) прямой загрузкой на портал по токену | `quantor.tender_calc.v1` |

База — «исходный код» объекта: кадр листа, оси, уровни, зоны, конструкции, стояки, размещение этажа в здании.
Расчёт — «коммит» системы: трассы и приборы в координатах базы, объёмы по этажам, вопросы. Повторная загрузка
расчёта той же системы — новая версия; прежние версии не меняются.

## Система координат (общая для обоих пакетов)

- **Вид** (`view`) — один план на странице PDF ревизии документа. Ключ вида:
  `view_key = "<revision_id>:<page_index>:<view>"` (UUID ревизии, номер страницы с 0, номер вида — как в Quantor, с 1). В примерах ниже `rev` — сокращение UUID ревизии; в настоящих файлах — полный UUID.
- **XY** — мм DXF вида движка (`frame = "view_dxf_mm"`): X вправо, **Y вверх**. Перевод в пункты PDF
  (от левого верхнего угла страницы): `pt = origin_pt + (x_mm, −y_mm) / mm_per_pdf_point`.
- **Z** — мм **от чистого пола этажа вида** (как `routes3d` движка). Поэтому один план типового этажа годится
  для всех этажей из `floors`. Абсолютная отметка этажа — `level.floor_elevation_mm` из базы.
- Здание: этаж ставится в общую систему корпуса (и объекта) преобразованием
  `p = R(rotation_deg) · p_вида + offset_mm`: сначала поворот вокруг начала кадра вида (`rotation_deg`, градусы
  **против часовой**), потом сдвиг `offset_mm`. Преобразование делает портал: поворот кратен 90° у листа,
  нарисованного повёрнутым относительно эталона группы (по подписям общих осей), плюс поворот группы при посадке
  на объект по ядрам (любой угол). `rotation_deg` в файлах необязателен, нет — 0. Тендерные навыки
  преобразование не применяют: пишут XY вида, портал размещает сам.
- Привязка тендерных координат (пункты листа, метры от осей, мм IFC) к кадру вида — **аффинно по общим осям**
  (`axes_fit.py` навыка `quantor-obmen`, ≥ 2 вертикальные и ≥ 2 горизонтальные оси или ≥ 3 пересечения).
  Качество привязки пишется в манифест расчёта (`fit[]`); `max_mm > 100` — предупреждение, `> 500` — отказ.

## Пакет «База объекта» — `quantor.object_base.v1`

ZIP `quantor-base-<номер выпуска>-<дата>.zip`:

```text
manifest.json
building.json
views/<dir>/view.json
views/<dir>/axes.json
views/<dir>/zones.json
views/<dir>/constructions.json
views/<dir>/risers.json          # если у листа есть реестр стояков
views/<dir>/plan.dxf             # только если при выпуске отмечено «с DXF»
coordination.json                # координационный файл: сетка осей и этажи (с 2026-11-18)
coordination.ifc                 # он же в IFC4
```

`<dir>` = `p<page_index:04d>-v<view>-<первые 8 знаков revision_id>`.

### manifest.json

```json
{
  "schema": "quantor.object_base.v1",
  "release": {"id": "uuid", "number": 3, "released_at": "2026-11-16T10:00:00Z",
              "released_by": "Фамилия И.О.", "comment": "Корп. 9 сек. 3, этажи 2–28"},
  "project": {"id": "uuid", "name": "342. ЖК Знаки"},
  "engine": {"version": "2026.11.13+…", "cad_walls": "cad_walls.v1.15", "cad_mep": "cad_mep.v16.5"},
  "units": "mm",
  "frame": "view_dxf_mm",
  "z_reference": "finished_floor",
  "views": [
    {"key": "rev:81:0", "dir": "views/p0081-v0-1a2b3c4d", "revision_id": "uuid", "document_id": "uuid",
     "document_title": "АР1.1", "page_index": 81, "view": 0, "sheet_label": "План 15 этажа",
     "dxf_sha256": "…", "corps": "9", "section": "3", "floors": ["15"]}
  ],
  "files": {"building.json": "<sha256>", "views/p0081-v0-1a2b3c4d/zones.json": "<sha256>"}
}
```

`floors` — подписи этажей, к которым относится план (из заголовка плана; типовой план — список). Нет данных —
пустой список, навык спрашивает человека.

### view.json

```json
{
  "schema": "quantor.object_base.view.v1",
  "key": "rev:81:0",
  "frame": {"mm_per_pdf_point": 70.556, "origin_pt": [120.5, 1610.25], "page_size_pt": [2384.0, 1684.0],
            "confirmed": true},
  "level": {"floor_elevation_mm": 50900, "floor_height_mm": 3000, "slab_thickness_mm": 200,
            "elevation_known": true, "floor_height_known": true, "slab_thickness_known": false},
  "placement": {"group_key": "9|3", "group_label": "Корпус 9, секция 3", "offset_mm": [0, 0],
                "rotation_deg": 0, "alignment": "reference", "alignment_axes": ["1", "9", "А", "Г"]},
  "bbox": [0, 0, 42000, 18000]
}
```

`*_known = false` — значение типовое (не из документации и не от человека); навык обязан это учесть.

### axes.json

```json
{"schema": "quantor.object_base.axes.v1",
 "axes": [{"label": "1", "orient": "vertical", "pos_mm": 0},
          {"label": "А", "orient": "horizontal", "pos_mm": 0}]}
```

Вертикальная ось — линия `x = pos_mm`, горизонтальная — `y = pos_mm`. Только принятые движком оси.

### zones.json — зоны (квартиры, помещения МОП, машино-места)

```json
{"schema": "quantor.object_base.zones.v1",
 "zones": [{"id": "uuid", "kind": "room_apartment", "apartment_no": "15.1", "room_mark": "1",
            "name": "Кухня-гостиная", "room_type": "living", "area_m2": 24.6,
            "points": [[0, 0], [6000, 0], [6000, 4100], [0, 4100]]}]}
```

`kind`: `room_apartment` | `room_mop` | `parking_space` (двери как зоны в базу не входят). `points` — одно
кольцо в мм кадра вида, без замыкающей точки. `area_m2` — площадь кольца.

### constructions.json — конструкции движка

`kind` — коды движка `cad_walls` (`masonry`, `monolith_wall`, …); `material` и `thickness_mm` — только принятые
человеком (номинал или принятое переопределение), иначе `null`.

```json
{"schema": "quantor.object_base.constructions.v1",
 "constructions": [{"id": "c12", "kind": "masonry", "material": "газобетон",
                    "thickness_mm": 200, "shell": [[0,0],[6000,0],[6000,200],[0,200]], "holes": []}],
 "openings": [{"id": "o3", "kind": "door", "host_id": "c12", "width_mm": 900,
               "center": [3000, 100], "direction": [1000, 0]}],
 "slab": {"shell": [[0,0],[42000,0],[42000,18000],[0,18000]]}}
```

`slab.shell` — основная (самая большая) часть плиты; `slab.parts` — все части плиты, включая основную,
только когда их больше одной (лист из двух корпусов), иначе ключа нет; поле аддитивное.

### risers.json — реестр стояков листа (ADR-0041), как в портале

```json
{"schema": "quantor.object_base.risers.v1",
 "risers": [{"system": "K1", "mark": "Ст К1-3", "dn_mm": 110, "role": "riser", "count": 1,
             "shaft_id": "ш5", "source": "ИОС3.1 л.4", "note": null}]}
```

### building.json — размещение всех видов выпуска

```json
{"schema": "quantor.object_base.building.v1",
 "floors": [{"view_key": "rev:81:0", "label": "15", "group_key": "9|3", "base_z_mm": 50900,
             "floor_height_mm": 3000, "offset_mm": [0, 0], "rotation_deg": 0,
             "alignment": "reference"}]}
```

### coordination.json и coordination.ifc — координационный файл

Общая сетка осей и этажи здания: «пространство», к которому привязываются модели и расчёты всех разделов.
Собирается при выпуске из тех же файлов, что лежат рядом: оси каждого вида (`axes.json`) переводятся в систему
здания по `building.json` (`p = R(rotation_deg) · p_вида + offset_mm`) и сводятся по подписи внутри группы
(корпус/секция). Положение оси поперёк - медиана по этажам, направление - у эталонного этажа группы. Заново
ничего не распознаётся. Несовмещённые виды (`alignment = none`) в сетку не входят, их этаж остаётся.

```json
{"schema": "quantor.object_base.coordination.v1", "units": "mm", "frame": "building_mm",
 "groups": [{"group_key": "9|3", "group_label": "Корпус 9, секция 3",
   "axes": [{"label": "1", "orient": "vertical", "point_mm": [0, 0], "direction": [0.0, 1.0],
             "views": 11, "spread_mm": 0}],
   "storeys": [{"label": "План 1 этажа", "base_z_mm": 0, "floor_height_mm": 4080,
                "view_keys": ["rev:5:1"]}]}],
 "doubts": ["Корпус 9, секция 3: ось Д расходится между этажами на 120 мм"]}
```

- `point_mm` + `direction` — ось линией в мм системы здания (оси под углом к осям X/Y тоже бывают: поворот
  группы при посадке на площадку, корпус, повёрнутый на сводном плане, — оси под углом к листу, cad_walls 1.19);
  `orient` — семья оси по направлению в здании (ближе к Y — `vertical`, к X — `horizontal`), точное направление —
  `direction`. В `axes.json` вида оси под углом не пишутся: там по-прежнему только вертикальные и горизонтальные.
- `views` — на скольких этажах ось есть; `spread_mm` — насколько эти этажи расходятся поперёк оси (качество
  совмещения). Расхождение больше 50 мм и ось меньше чем на половине этажей попадают в `doubts`.
- `coordination.ifc` — IFC4 в мм: участок, здание на группу, этажи (`IfcBuildingStorey.Elevation` =
  `base_z_mm`), на каждом этаже `IfcGrid` (вертикальные оси вида — U, горизонтальные — V; отрезки на 3 м
  за крайние пересечения). Открывается в Revit/Navisworks/любом просмотрщике IFC, к нему привязывают модели
  разделов. GlobalId выводятся из id выпуска.

## Пакет «Расчёт» — `quantor.tender_calc.v1`

ZIP (любое имя), не больше 50 МБ и 2000 файлов:

```text
manifest.json
quantities.json
questions.json        # необязательно
views/<любое>.json    # геометрия по видам; один файл — один вид
```

Других файлов нет: xlsx, pdf и вложения не принимаются.

### manifest.json

```json
{
  "schema": "quantor.tender_calc.v1",
  "project_id": "uuid",
  "base": {"release_id": "uuid", "manifest_sha256": "<sha256 manifest.json базы>"},
  "calc": {"discipline": "mech", "system": "heating", "title": "Отопление жилой части"},
  "version": {"label": "v3", "message": "Перестроены лучи 15 этажа",
              "author": "Кузьмин А.А.", "created_at": "2026-11-16T12:00:00Z"},
  "producer": {"skill": "raschet-otopleniya", "skill_ref": "2026-11-16", "tool": "quantor-obmen 1.0"},
  "fit": [{"view_key": "rev:81:0", "method": "axes_affine", "axes": ["1", "9", "А", "Г"],
           "rms_mm": 12, "max_mm": 31}],
  "files": {"quantities.json": "<sha256>", "views/p0081.json": "<sha256>"}
}
```

- **Репозиторий расчёта** в портале = `(project_id, discipline, system, title)`; новая загрузка с тем же
  ключом — новая версия (номер выдаёт портал, `label` — подпись автора). Тот же ZIP повторно — та же версия.
- `discipline`: `mech` | `eom` | `ss`.
- `system` (закрытый список v1):
  - `mech`: `heating`, `water_supply`, `sewage`, `storm_drain`, `fire_sprinkler`, `fire_hydrant`, `dry_pipe`,
    `ventilation`, `smoke_control`, `conditioning`, `cooling`, `itp`, `mech_other`;
  - `eom`: `power`, `lighting`, `grounding`, `lightning`, `eom_other`;
  - `ss`: `ss_network`, `ss_security`, `ss_fire_alarm`, `ss_dispatch`, `ss_other`.
- `fit[].method`: `axes_affine` | `identity` (навык считал прямо в мм базы).

### views/*.json — геометрия вида (`quantor.tender_calc.view.v1`)

Надмножество `routes3d.v2` движка: портал рисует его тем же кодом.

```json
{
  "schema": "quantor.tender_calc.view.v1",
  "view_key": "rev:81:0",
  "dxf_sha256": "…",
  "floors": ["4", "5", "6"],
  "polylines": [
    {"id": "T1-15.1-a", "system": "heating", "layer": "T-OV-T1", "kind": "route", "shape": "round",
     "dn_mm": 20, "pts": [[1200, 3400, 300], [5200, 3400, 300]], "insulation_mm": 0, "slope": null,
     "mark": null, "apt": "15.1", "note": "луч к конвектору КВ-2"}
  ],
  "elements": [
    {"id": "KV-15.1-2", "system": "heating", "type": "terminal", "subtype": "convector", "layer": "T-OV-T1",
     "pos": [5200, 3400, 100], "axis": [1000, 0, 0], "w_mm": 1500, "length_mm": 300, "h_mm": 110,
     "dn_mm": null, "mark": "КВ-2", "apt": "15.1"}
  ]
}
```

- `floors` — этажи, на которые распространяется этот план (типовой — несколько). Объёмы на этажи — в
  `quantities.json`, портал геометрию не пересчитывает.
- `polylines[].kind`: `route` | `jumper` | `riser` | `leadin` | `cable` | `tray` | `duct`.
  `shape`: `round` (Ø `dn_mm` — наружный) | `rect` (`w_mm` × `h_mm`) | `null` — линия.
- `elements[].type`: `fitting` | `valve` | `sleeve` | `terminal` | `equipment`. `subtype` — свободная строка
  ≤ 32 знаков; для ЭОМ/СС: `panel`, `luminaire`, `socket`, `switch`, `junction_box`, `detector`,
  `camera`, `reader`, `speaker`. Коробка прибора — `w_mm` (вдоль X) × `length_mm` (вдоль Y) × `h_mm`
  с центром `pos`; `axis` — единичный вектор × 1000.
- `layer` — `T-<РАЗДЕЛ>-<СИСТЕМА>`: `T-OV-T1`, `T-VK-V1`, `T-VK-K1`, `T-PT-AUP`, `T-PT-VPV`, `T-OV-VENT`,
  `T-PD-DU`, `T-KV-FR`, `T-EOM-CAB`, `T-EOM-TRAY`, `T-EOM-LIGHT`, `T-SS-CAB`… Префикс `T-` отличает расчёт от
  трасс движка (`M-`).
- `id` — уникален внутри файла; ссылки из `quantities.json` и вопросов — по нему.

### quantities.json — объёмы (без цен)

```json
{
  "schema": "quantor.tender_calc.quantities.v1",
  "rows": [
    {"code": "OV-PEX-16", "group": "Трубы", "name": "Труба PE-Xa 16×2,0", "unit": "м", "qty": 1234.5,
     "basis": "geometry", "per_floor": [{"floor": "15", "qty": 45.2}], "view_keys": ["rev:81:0"],
     "note": "запас 10 % включён"}
  ]
}
```

- `basis`: `geometry` (по трассам пакета) | `schedule` (по схеме/спецификации ПД) | `rule` (норма с источником в
  `note`) | `assumption` (допущение — обязательно в `questions.json`).
- `unit`: `м`, `м2`, `м3`, `шт`, `компл`, `т`, `кг`, `точка`.
- **Цен нет.** Ключи и значения про стоимость (`price`, `cost`, `amount`, `currency`, `vat`, «цена», «стоим»,
  «руб», «₽», «НДС») в любом файле пакета — отказ загрузки. ПЗ и расценка остаются в TENDER/HUBTender.

### questions.json

```json
{"schema": "quantor.tender_calc.questions.v1",
 "rows": [{"text": "Шаг конвекторов на витражах не задан, принят 1,5 м", "ref": "АР1.1 л.82",
           "ids": ["KV-15.1-2"]}]}
```

## Проверки портала при загрузке

1. ZIP: без путей вне корня, без ссылок, распакованный объём ≤ 200 МБ, сжатие ≤ 1:100.
2. Схемы всех файлов; `files` манифеста совпадают с sha256 содержимого.
3. `project_id` — этот проект; `base.release_id` — выпуск этого проекта.
4. Каждый `view_key` есть в выпуске базы. Если текущий `dxf_sha256` вида в портале другой — расчёт принят с
   предупреждением «база устарела» (вид перестроен движком после выпуска).
5. Запрет цен — по всем строкам и ключам.
6. `fit[].max_mm > 500` — отказ; `> 100` — предупреждение.
7. Объекты вида за рамкой `bbox` вида базы больше чем на 1 м — предупреждение `out_of_bbox` (проверка — для
   выпусков, где портал сохранил рамку вида).

## Совместимость

Новое поле — только аддитивно с той же схемой; несовместимое — `…v2`, портал читает обе версии.
