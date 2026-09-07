/**
 * Преобразование координат просмотрщика.
 *
 * Канон хранения — нормализованные координаты от левого верхнего угла листа, значения
 * в диапазоне [0, 1] (ADR-0008). Экранные пиксели появляются только в момент отрисовки,
 * и только здесь.
 *
 * Модуль намеренно без зависимостей и без обращений к DOM: это чистые функции, которые
 * можно проверить тестами и вызывать хоть из воркера. Ошибка в них проявляется как
 * «разметка не совпадает с чертежом» — самый дорогой класс дефектов в таком продукте.
 */

/** Прямоугольник в нормализованном пространстве листа: [x0, y0, x1, y1]. */
export type NormalizedRect = readonly [number, number, number, number];

/** Точка в нормализованном пространстве листа. */
export interface NormalizedPoint {
  readonly x: number;
  readonly y: number;
}

/** Точка в пикселях области отрисовки. */
export interface ScreenPoint {
  readonly x: number;
  readonly y: number;
}

/** Прямоугольник в пикселях области отрисовки. */
export interface ScreenRect {
  readonly x: number;
  readonly y: number;
  readonly width: number;
  readonly height: number;
}

/** Допустимые повороты страницы PDF. */
export type Rotation = 0 | 90 | 180 | 270;

/**
 * Положение листа на экране.
 *
 * Лист уже отмасштабирован и размещён: сюда приходит его прямоугольник в пикселях
 * и поворот. Наложение областей ничего не знает ни о камере, ни о зуме — только об этом.
 */
export interface SheetPlacement {
  /** Левый верхний угол листа в пикселях области отрисовки. */
  readonly x: number;
  readonly y: number;
  /** Размер отрисованного листа в пикселях — уже с учётом поворота. */
  readonly width: number;
  readonly height: number;
  readonly rotation: Rotation;
}

export const isRotation = (value: number): value is Rotation =>
  value === 0 || value === 90 || value === 180 || value === 270;

/** Приводит произвольный угол к одному из четырёх допустимых. */
export const normalizeRotation = (value: number): Rotation => {
  const wrapped = (((Math.round(value / 90) * 90) % 360) + 360) % 360;
  return isRotation(wrapped) ? wrapped : 0;
};

export const clamp = (value: number, min: number, max: number): number =>
  Math.min(Math.max(value, min), max);

const clamp01 = (value: number): number => clamp(value, 0, 1);

/**
 * Поворачивает точку внутри единичного квадрата.
 *
 * Поворот страницы задан в PDF и применяется при отрисовке, поэтому координаты области,
 * записанные для неповёрнутой страницы, нужно повернуть так же. Без этого разметка
 * на повёрнутых листах уезжает — а такие листы в проектной документации обычны.
 */
export const rotateUnitPoint = (point: NormalizedPoint, rotation: Rotation): NormalizedPoint => {
  switch (rotation) {
    case 90:
      return { x: 1 - point.y, y: point.x };
    case 180:
      return { x: 1 - point.x, y: 1 - point.y };
    case 270:
      return { x: point.y, y: 1 - point.x };
    default:
      return point;
  }
};

/** Обратный поворот: из координат отрисованного листа обратно в координаты хранения. */
export const unrotateUnitPoint = (point: NormalizedPoint, rotation: Rotation): NormalizedPoint => {
  switch (rotation) {
    case 90:
      return { x: point.y, y: 1 - point.x };
    case 180:
      return { x: 1 - point.x, y: 1 - point.y };
    case 270:
      return { x: 1 - point.y, y: point.x };
    default:
      return point;
  }
};

/** Нормализованная точка → пиксели области отрисовки. */
export const toScreenPoint = (point: NormalizedPoint, placement: SheetPlacement): ScreenPoint => {
  const rotated = rotateUnitPoint(point, placement.rotation);
  return {
    x: placement.x + rotated.x * placement.width,
    y: placement.y + rotated.y * placement.height,
  };
};

/** Пиксели области отрисовки → нормализованная точка листа. */
export const toNormalizedPoint = (
  point: ScreenPoint,
  placement: SheetPlacement,
): NormalizedPoint => {
  const rotated = {
    x: placement.width === 0 ? 0 : (point.x - placement.x) / placement.width,
    y: placement.height === 0 ? 0 : (point.y - placement.y) / placement.height,
  };
  const unrotated = unrotateUnitPoint(rotated, placement.rotation);
  return { x: unrotated.x, y: unrotated.y };
};

/**
 * Нормализованный прямоугольник → прямоугольник на экране.
 *
 * После поворота углы меняются местами, поэтому результат нормализуется по минимуму
 * и максимуму: ширина и высота обязаны остаться положительными.
 */
export const toScreenRect = (rect: NormalizedRect, placement: SheetPlacement): ScreenRect => {
  const [x0, y0, x1, y1] = rect;
  const first = toScreenPoint({ x: x0, y: y0 }, placement);
  const second = toScreenPoint({ x: x1, y: y1 }, placement);

  return {
    x: Math.min(first.x, second.x),
    y: Math.min(first.y, second.y),
    width: Math.abs(second.x - first.x),
    height: Math.abs(second.y - first.y),
  };
};

/** Полигон в нормализованных координатах → точки на экране. */
export const toScreenPolygon = (
  points: readonly (readonly [number, number])[],
  placement: SheetPlacement,
): ScreenPoint[] => points.map(([x, y]) => toScreenPoint({ x, y }, placement));

/** Приводит прямоугольник к виду, где первый угол левее и выше второго. */
export const normalizeRect = (rect: NormalizedRect): NormalizedRect => {
  const [x0, y0, x1, y1] = rect;
  return [
    clamp01(Math.min(x0, x1)),
    clamp01(Math.min(y0, y1)),
    clamp01(Math.max(x0, x1)),
    clamp01(Math.max(y0, y1)),
  ];
};

export const rectContains = (rect: NormalizedRect, point: NormalizedPoint): boolean => {
  const [x0, y0, x1, y1] = normalizeRect(rect);
  return point.x >= x0 && point.x <= x1 && point.y >= y0 && point.y <= y1;
};

export const rectArea = (rect: NormalizedRect): number => {
  const [x0, y0, x1, y1] = normalizeRect(rect);
  return (x1 - x0) * (y1 - y0);
};

/**
 * Ищет область под курсором.
 *
 * Из перекрывающихся побеждает самая маленькая: крупный блок обычно окружает мелкие,
 * и выбирать нужно то, во что пользователь целился.
 *
 * Перебор линейный — на листе сотни областей, и это дёшево. Когда их станут тысячи,
 * сюда встанет пространственный индекс, а сигнатура функции не изменится.
 */
export const hitTest = <T extends { readonly coords_norm: readonly number[] }>(
  regions: readonly T[],
  point: NormalizedPoint,
): T | null => {
  let best: T | null = null;
  let bestArea = Number.POSITIVE_INFINITY;

  for (const region of regions) {
    const coords = region.coords_norm;
    if (coords.length !== 4) continue;

    const rect = [coords[0], coords[1], coords[2], coords[3]] as unknown as NormalizedRect;
    if (!rectContains(rect, point)) continue;

    const area = rectArea(rect);
    if (area < bestArea) {
      best = region;
      bestArea = area;
    }
  }

  return best;
};

/**
 * Прямоугольник отрисованной страницы.
 *
 * Единственный правильный источник размера — сам документ, а не растр распознавалки.
 * Проверено на эталонном пакете: все 77 страниц нормализованы относительно уже
 * повёрнутой страницы (`page.rect`), а её растр сделан с плотностью, которая ещё и
 * не постоянна — 4,17 px/pt на одних листах и 3,16 на других. Брать размер из
 * `width_px` значило бы промахнуться в разы, а на повёрнутых листах ещё и развернуть
 * разметку поперёк чертежа.
 *
 * Поэтому поворот здесь нулевой: pdf.js уже применил `/Rotate`, и координаты областей
 * записаны в той же, конечной системе. Механизм поворота остаётся в модуле для формата
 * пакета v2, если тот начнёт хранить координаты до поворота.
 *
 * Округление повторяет формулу бэкенда (`floor` в физических пикселях): холст страницы
 * и холст слоя обязаны совпадать пиксель в пиксель, иначе разметка «плывёт» на дробных
 * масштабах.
 */
export const placeRenderedPage = (
  page: { readonly width: number; readonly height: number },
  scale: number,
  devicePixelRatio = 1,
): SheetPlacement => {
  const ratio = devicePixelRatio > 0 ? devicePixelRatio : 1;

  return {
    x: 0,
    y: 0,
    width: Math.floor(page.width * scale * ratio) / ratio,
    height: Math.floor(page.height * scale * ratio) / ratio,
    rotation: 0,
  };
};

/** Размер листа в пикселях при заданном масштабе и повороте. */
export const placeSheet = (
  sheet: { readonly widthPx: number; readonly heightPx: number; readonly rotation: Rotation },
  options: { readonly scale: number; readonly offsetX: number; readonly offsetY: number },
): SheetPlacement => {
  const swapped = sheet.rotation === 90 || sheet.rotation === 270;
  const width = (swapped ? sheet.heightPx : sheet.widthPx) * options.scale;
  const height = (swapped ? sheet.widthPx : sheet.heightPx) * options.scale;

  return {
    x: options.offsetX,
    y: options.offsetY,
    width,
    height,
    rotation: sheet.rotation,
  };
};
