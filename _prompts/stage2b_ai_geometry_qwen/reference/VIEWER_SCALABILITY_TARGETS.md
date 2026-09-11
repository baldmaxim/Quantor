# Viewer scalability before AI overlays

Текущий full-page подход при A1 ~266% и DPR ~1.5 может создавать десятки миллионов pixels на
каждый canvas. Четыре full-page canvas дают неприемлемый memory pressure.

## Главное правило точности

Точность геометрической координаты клика **не должна зависеть от raster canvas resolution**:

```text
screen pointer → camera inverse transform → sheet normalized/PDF coordinates
```

Raster resolution отвечает за визуальную резкость, а не за математическую coordinate truth.

## Инкрементальный путь

1. Сначала сделать regions/scale/measurement/AI vector overlays viewport-sized, а не
   full-page sized.
2. Добавить spatial culling/index и рисовать только видимые primitives.
3. Перемерить A1 @ 266%.
4. Если base PDF canvas всё ещё не проходит memory/frame budget — реализовать viewport/tile
   PDF rendering через расширение `RenderBackend`, не ломая camera/coordinate core.

## Live check

На эталонном листе @ 266%:

- 30 с панорамирования во все стороны;
- нет белых вспышек/старых фрагментов;
- measurement/region/candidate не отрываются;
- после остановки pan CPU возвращается к покою;
- memory не растёт монотонно от каждого pan;
- coordinate hit remains stable;
- никаких network/API writes на pointermove.

Не объявлять PASS только по unit tests.
