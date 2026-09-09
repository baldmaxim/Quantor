/**
 * Преобразование координат измерений: нормализованные ↔ точки PDF.
 *
 * Зеркало серверного `app/services/geometry/transform.py`. Нужно для предварительного
 * показа: пользователь тянет линию и сразу видит длину, не дожидаясь ответа сервера.
 *
 * **Источник правды — сервер.** Здесь считается то, что показывается во время рисования;
 * сохранённая величина приходит с сервера и заменяет предварительную. Локальное значение
 * не имеет права остаться на экране под видом сохранённого, если запрос не прошёл.
 *
 * ## Почему две реализации не расходятся
 *
 * Обе работают в IEEE-754 binary64, и одинаковая последовательность операций даёт
 * одинаковый результат до последнего бита (ADR-0017). Отсюда правило: **порядок операций —
 * часть контракта**. Сумма длин звеньев накапливается слева направо, площадь обходит
 * вершины по возрастанию индекса. Переставлять слагаемые нельзя.
 *
 * Совпадение проверяется общими векторами `tests/fixtures/coordinate_vectors.json` —
 * тем же файлом, что читают тесты на Python, — и сравнение идёт на точное равенство.
 *
 * Поворот здесь не применяется: он уже учтён в размерах страницы (ADR-0016), а
 * нормализованные координаты относятся к уже повёрнутой странице (ADR-0008). Механизм
 * поворота остаётся в `coordinates.ts` под будущий формат пакета v2 и к измерениям
 * отношения не имеет.
 */

import type { NormalizedPoint } from '@/lib/viewer/coordinates';

/** Точка в точках PDF отображённой страницы, начало в левом верхнем углу. */
export interface PdfDisplayPoint {
  readonly x: number;
  readonly y: number;
}

/**
 * Размер отображённой страницы в точках PDF.
 *
 * Отдельный тип, а не пара чисел: перепутать ширину с высотой на прямоугольной странице
 * слишком легко, а результат такой ошибки — правдоподобное, но неверное число.
 */
export interface PageGeometryValue {
  readonly displayWidthPt: number;
  readonly displayHeightPt: number;
}

/** Отказ преобразования: те же условия, что проверяет сервер. */
export class GeometryError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'GeometryError';
  }
}

/**
 * Разбирает геометрию из ответа API.
 *
 * Размеры приходят строками: `JSON.parse` превратил бы их в число и потерял каноническую
 * десятичную запись, на которой построен отпечаток. Здесь — граница «строка → число»,
 * симметричная серверной «Decimal → float» (ADR-0017).
 */
export const parsePageGeometry = (raw: {
  readonly display_width_pt: string | number;
  readonly display_height_pt: string | number;
}): PageGeometryValue => {
  const geometry = {
    displayWidthPt: Number(raw.display_width_pt),
    displayHeightPt: Number(raw.display_height_pt),
  };
  requirePage(geometry);
  return geometry;
};

const requireFinite = (value: number, what: string): void => {
  if (!Number.isFinite(value)) {
    throw new GeometryError(`${what}: ожидается конечное число`);
  }
};

/** Страница обязана быть положительной: на её размер делят. */
const requirePage = (geometry: PageGeometryValue): void => {
  requireFinite(geometry.displayWidthPt, 'ширина страницы');
  requireFinite(geometry.displayHeightPt, 'высота страницы');
  if (geometry.displayWidthPt <= 0 || geometry.displayHeightPt <= 0) {
    throw new GeometryError('Размер страницы должен быть положительным');
  }
};

/** Границы 0 и 1 допустимы: угол листа — законная точка, а не ошибка ввода. */
const requireNormalized = (point: NormalizedPoint): void => {
  requireFinite(point.x, 'x');
  requireFinite(point.y, 'y');
  if (point.x < 0 || point.x > 1 || point.y < 0 || point.y > 1) {
    throw new GeometryError(`Нормализованная точка вне листа: (${point.x}, ${point.y})`);
  }
};

/** Нормализованная точка → точка PDF. Умножение и ничего больше. */
export const normalizedToPdfDisplay = (
  point: NormalizedPoint,
  geometry: PageGeometryValue,
): PdfDisplayPoint => {
  requirePage(geometry);
  requireNormalized(point);
  return {
    x: point.x * geometry.displayWidthPt,
    y: point.y * geometry.displayHeightPt,
  };
};

/**
 * Точка PDF → нормализованная точка.
 *
 * Результат не зажимается в [0, 1]: точка за пределами страницы — это ошибка вызывающего,
 * и молча подвинуть её к краю значило бы получить правдоподобную геометрию вместо отказа.
 */
export const pdfDisplayToNormalized = (
  point: PdfDisplayPoint,
  geometry: PageGeometryValue,
): NormalizedPoint => {
  requirePage(geometry);
  requireFinite(point.x, 'x');
  requireFinite(point.y, 'y');
  return {
    x: point.x / geometry.displayWidthPt,
    y: point.y / geometry.displayHeightPt,
  };
};

/**
 * Расстояние между точками в точках PDF.
 *
 * `Math.hypot`, а не корень из суммы квадратов: он не переполняется на больших значениях.
 * Серверу соответствует `math.hypot` — на одних входах они дают побитово одно и то же.
 */
export const distancePdfPoints = (first: PdfDisplayPoint, second: PdfDisplayPoint): number => {
  requireFinite(first.x, 'x');
  requireFinite(first.y, 'y');
  requireFinite(second.x, 'x');
  requireFinite(second.y, 'y');
  return Math.hypot(second.x - first.x, second.y - first.y);
};

/**
 * Длина ломаной в точках PDF.
 *
 * Считать длину в нормализованном пространстве нельзя: на прямоугольной странице шаг 0,1
 * по X и 0,1 по Y — разные расстояния. Точки сначала переводятся, и только потом измеряются.
 *
 * Сумма накапливается слева направо. Порядок — часть контракта.
 */
export const polylineLengthPdfPoints = (
  points: readonly NormalizedPoint[],
  geometry: PageGeometryValue,
): number => {
  if (points.length < 2) {
    throw new GeometryError(`Для длины нужно минимум две точки, передано ${points.length}`);
  }

  const projected = points.map((point) => normalizedToPdfDisplay(point, geometry));

  // Обход через `previous`, а не по индексу: индексация массива даёт `T | undefined`,
  // и глушить это утверждением типа значило бы прятать реальный случай пустого входа.
  let total = 0;
  let previous: PdfDisplayPoint | undefined;
  for (const current of projected) {
    if (previous !== undefined) {
      total += distancePdfPoints(previous, current);
    }
    previous = current;
  }
  return total;
};

/**
 * Площадь многоугольника в квадратных точках PDF, формула шнурков.
 *
 * Обход вершин по возрастанию индекса с замыканием последней на нулевую; порядок — часть
 * контракта. Результат по модулю: направление обхода задаёт знак, а площадь отрицательной
 * не бывает.
 *
 * Самопересечения не проверяются: формула даёт на них разность площадей, а не отказ.
 * Политика для таких фигур — вопрос правил подсчёта, а не преобразования координат.
 */
export const polygonAreaPdfPoints2 = (
  points: readonly NormalizedPoint[],
  geometry: PageGeometryValue,
): number => {
  if (points.length < 3) {
    throw new GeometryError(`Для площади нужно минимум три точки, передано ${points.length}`);
  }

  const projected = points.map((point) => normalizedToPdfDisplay(point, geometry));
  const first = projected[0];
  if (first === undefined) {
    throw new GeometryError('Пустой список вершин');
  }

  // Пары вершин строятся заранее — так порядок слагаемых виден и совпадает с серверным:
  // сначала соседние по возрастанию индекса, замыкание на нулевую вершину последним.
  const pairs: [PdfDisplayPoint, PdfDisplayPoint][] = [];
  let previous = first;
  for (const current of projected.slice(1)) {
    pairs.push([previous, current]);
    previous = current;
  }
  pairs.push([previous, first]);

  let total = 0;
  for (const [current, following] of pairs) {
    total += current.x * following.y - following.x * current.y;
  }
  return Math.abs(total) / 2;
};
