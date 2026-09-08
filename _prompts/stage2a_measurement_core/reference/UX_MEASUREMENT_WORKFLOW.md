# UX Stage 2A — Kreo-like workflow без копирования дизайна

## Workspace

```text
┌──────────────────┬────────────────────────────────────┬────────────────────┐
│ TAKEOFF ITEMS    │              DRAWING               │ INSPECTOR          │
│                  │                                    │                    │
│ Двери            │        PDF base layer              │ Measurement        │
│ Перегородка ПГ-1 │        recognition layer           │ value              │
│ Пол              │        measurement layer           │ scale              │
│                  │                                    │ source             │
│ + New item       │                                    │ sheet              │
└──────────────────┴────────────────────────────────────┴────────────────────┘

Toolbar: Select | Pan | Count | Line | Polyline | Area | Scale
```

## Требования к инструментам

- `Esc` — отменить draft/текущий инструмент.
- `Enter` — закончить polyline/polygon.
- `Backspace` — удалить последнюю draft-точку.
- `Delete` — удалить выбранное сохранённое measurement с подтверждением/undo policy.
- Space/middle mouse — временный pan.
- Pointer move во время drawing/drag **не делает API-запрос** и не обновляет весь React tree.
- Persist — по завершению measurement или drag-end.
- Count должен ощущаться мгновенно; разрешён optimistic local add + bounded batch flush.

## Layering

```text
PDF canvas
Recognition Canvas2D
Measurement Canvas2D (отдельный)
Selected handles / small interaction DOM only if justified
```

Region overlay и measurement overlay не смешивать.

## Scale UX

1. Пользователь выбирает Scale.
2. Кликает A и B по известному размеру.
3. Вводит `6000` и `mm` (или `6` и `m`).
4. Portal показывает рассчитанный scale factor и область применения.
5. Только после подтверждения calibration сохраняется.
6. Для length/area inspector всегда показывает calibration, использованную measurement.

Надпись `М 1:100` можно показать пользователю как текст recognition evidence, но Stage 2A не
имеет права автоматически принять её за масштаб.

## Quantity UX

- Count → `N шт.`
- Line/Polyline → `x.xx м`
- Area → `x.xx м²`
- No scale → `—`, warning «Масштаб не задан».
- Result from server is authoritative; локальный preview допускается, но не должен
  маскироваться под сохранённое значение при ошибке API.

## Производительность

Пан/зум не должен перерендерить PDF из-за изменения Measurement. Base page rendering,
recognition overlay, measurement overlay, interaction state — отдельные ответственности.
Canvas2D сохраняется до benchmark, доказывающего необходимость WebGL.
