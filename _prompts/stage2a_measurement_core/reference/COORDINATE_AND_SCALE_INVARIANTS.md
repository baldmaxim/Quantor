# Инварианты координат и масштаба Stage 2A

Это наиболее критичный reference всего этапа.

## 1. Три пространства координат

### Stored normalized display space

То, что уже хранит Quantor:

```text
x_norm, y_norm ∈ [0,1]
origin = top-left
relative to the displayed/rotated page
```

Оно остаётся удобным каноном для Region и Measurement geometry.

### Canonical PDF display space

Новое серверное пространство:

```text
x_pt ∈ [0, display_width_pt]
y_pt ∈ [0, display_height_pt]
origin = top-left
unit = PDF point (1/72 inch as document coordinate unit)
rotation already reflected in display_width/display_height
```

**Не применять rotation второй раз** к legacy-v1 normalized coordinates.

### Metric space

После калибровки:

```text
mm_per_pt
```

Внутренний физический канон — миллиметр и квадратный миллиметр. UI может показывать м и м².

## 2. Правильное преобразование

```text
x_pt = x_norm * display_width_pt
y_pt = y_norm * display_height_pt
```

Длина считается в PDF display points, затем умножается на `mm_per_pt`.

Площадь сначала считается в pt², затем умножается на `mm_per_pt²`.

Никогда не считать диагональную длину напрямую в normalized-space.

## 3. Калибровка по известному размеру

Пользователь задаёт A, B и фактическое расстояние D:

```text
page_distance_pt = distance(to_pdf(A), to_pdf(B))
mm_per_pt = known_distance_mm / page_distance_pt
```

Нулевой/слишком короткий сегмент отвергается.

## 4. На одном листе может быть несколько масштабов

Лист может содержать план 1:100 и узел 1:20. Поэтому модель данных **не должна** исходить
из одного вечного scale на Sheet.

Минимум необходимо позволить:

- default calibration for whole sheet;
- несколько calibration records;
- optional local/region scope в модели данных;
- Measurement явно хранит `scale_calibration_id` для length/area;
- изменение default scale не должно молча менять старые Measurements.

Даже если UI Stage 2A сначала полноценно поддерживает только default + ручной выбор другой
калибровки, схема должна не блокировать локальные масштабы.

## 5. Calibration immutable/versioned

Калибровка является доказательством. Изменить 6000 → 6200 в той же строке нельзя.
Создаётся новая calibration, старая остаётся для воспроизводимости. Перепривязка существующих
Measurements — отдельное явное действие, а не side effect.

## 6. Scale status

- Count не требует scale.
- Line/Polyline/Polygon можно сохранить как геометрию без scale, но физическое quantity
  тогда должно быть `unavailable`, а UI показывает «масштаб не задан».
- Нельзя подставлять предполагаемый `1:100` из текста без явного Stage 2B алгоритма.

## 7. Cross-runtime test vectors

Python backend и TypeScript frontend должны прогонять **одни и те же JSON test vectors**:
portrait, landscape, diagonal, boundary points, fractional dimensions, rotated-display case.
Так ловится расхождение двух реализаций до живого проекта.
