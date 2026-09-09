/**
 * Совпадение с сервером на общих векторах.
 *
 * Читается тот же файл `tests/fixtures/coordinate_vectors.json`, что и тестами на Python,
 * и сравнение идёт на точное равенство — без `toBeCloseTo`. Допуск скрыл бы расхождение
 * двух реализаций, ради поимки которого векторы и заведены (ADR-0017).
 */

import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';

import { describe, expect, it } from 'vitest';

import type { NormalizedPoint } from '@/lib/viewer/coordinates';
import {
  GeometryError,
  distancePdfPoints,
  normalizedToPdfDisplay,
  parsePageGeometry,
  pdfDisplayToNormalized,
  polygonAreaPdfPoints2,
  polylineLengthPdfPoints,
  type PageGeometryValue,
} from '@/lib/viewer/measurement';

interface RawPage {
  readonly display_width_pt: number;
  readonly display_height_pt: number;
}

interface Vectors {
  readonly version: number;
  readonly pages: Record<string, RawPage>;
  readonly to_pdf: { name: string; page: string; point: number[]; expected: number[] }[];
  readonly roundtrip: { page: string; point: number[] }[];
  readonly length: { name: string; page: string; points: number[][]; expected_pt: number }[];
  readonly area: { name: string; page: string; points: number[][]; expected_pt2: number }[];
}

// Путь от apps/web до корня репозитория: файл общий и переезжать не должен.
const VECTORS_PATH = resolve(__dirname, '../../../../../tests/fixtures/coordinate_vectors.json');

const vectors: Vectors = JSON.parse(readFileSync(VECTORS_PATH, 'utf-8'));

const pages: Record<string, PageGeometryValue> = Object.fromEntries(
  Object.entries(vectors.pages).map(([name, raw]) => [
    name,
    { displayWidthPt: raw.display_width_pt, displayHeightPt: raw.display_height_pt },
  ]),
);

/** Страница из векторов. Отсутствие — испорченный файл, а не повод для утверждения типа. */
const pageOf = (name: string): PageGeometryValue => {
  const page = pages[name];
  if (page === undefined) {
    throw new Error(`в векторах нет страницы «${name}»`);
  }
  return page;
};

const pointOf = (raw: number[] | undefined): NormalizedPoint => {
  const x = raw?.[0];
  const y = raw?.[1];
  if (x === undefined || y === undefined) {
    throw new Error('точка в векторах должна иметь две координаты');
  }
  return { x, y };
};

const toPoints = (raw: number[][]): NormalizedPoint[] => raw.map(pointOf);

describe('общие векторы преобразования координат', () => {
  it('файл векторов найден и его версия та, что ожидается', () => {
    expect(vectors.version).toBe(1);
    expect(Object.keys(vectors.pages).length).toBeGreaterThan(0);
  });

  it.each(vectors.to_pdf)('нормализованные → точки PDF: $name', (testCase) => {
    const result = normalizedToPdfDisplay(pointOf(testCase.point), pageOf(testCase.page));

    expect([result.x, result.y]).toEqual(testCase.expected);
  });

  it.each(vectors.roundtrip)('туда и обратно: $page $point', (testCase) => {
    const geometry = pageOf(testCase.page);
    const source = pointOf(testCase.point);

    const back = pdfDisplayToNormalized(normalizedToPdfDisplay(source, geometry), geometry);

    // Точное равенство: «примерно то же» здесь означало бы накопление ошибки при
    // каждом перетаскивании вершины.
    expect(back.x).toBe(source.x);
    expect(back.y).toBe(source.y);
  });

  it.each(vectors.length)('длина ломаной: $name', (testCase) => {
    const result = polylineLengthPdfPoints(toPoints(testCase.points), pageOf(testCase.page));

    expect(result).toBe(testCase.expected_pt);
  });

  it.each(vectors.area)('площадь: $name', (testCase) => {
    const result = polygonAreaPdfPoints2(toPoints(testCase.points), pageOf(testCase.page));

    expect(result).toBe(testCase.expected_pt2);
  });
});

describe('ловушка прямоугольной страницы', () => {
  it('одинаковый шаг по X и по Y — разные расстояния', () => {
    // Причина, по которой старый units_per_normalized был математически неверен.
    const page: PageGeometryValue = { displayWidthPt: 3000, displayHeightPt: 4000 };

    const horizontal = polylineLengthPdfPoints(
      [
        { x: 0, y: 0 },
        { x: 0.1, y: 0 },
      ] as NormalizedPoint[],
      page,
    );
    const vertical = polylineLengthPdfPoints(
      [
        { x: 0, y: 0 },
        { x: 0, y: 0.1 },
      ] as NormalizedPoint[],
      page,
    );

    expect(horizontal).toBe(300);
    expect(vertical).toBe(400);
  });
});

describe('разбор геометрии из ответа API', () => {
  it('строки становятся числами', () => {
    const geometry = parsePageGeometry({
      display_width_pt: '595.2760',
      display_height_pt: '841.8900',
    });

    expect(geometry.displayWidthPt).toBe(595.276);
    expect(geometry.displayHeightPt).toBe(841.89);
  });

  it('нулевая страница отвергается на границе', () => {
    expect(() => parsePageGeometry({ display_width_pt: '0', display_height_pt: '100' })).toThrow(
      GeometryError,
    );
  });
});

describe('проверка входа', () => {
  const page: PageGeometryValue = { displayWidthPt: 1000, displayHeightPt: 1000 };

  it.each([Number.NaN, Number.POSITIVE_INFINITY, Number.NEGATIVE_INFINITY])(
    'неконечная координата отвергается: %s',
    (value) => {
      expect(() => normalizedToPdfDisplay({ x: value, y: 0.5 } as NormalizedPoint, page)).toThrow(
        GeometryError,
      );
    },
  );

  it.each([
    [-0.001, 0.5],
    [1.001, 0.5],
    [0.5, -1],
    [0.5, 2],
  ])('точка вне листа отвергается: (%s, %s)', (x, y) => {
    expect(() => normalizedToPdfDisplay({ x, y } as NormalizedPoint, page)).toThrow(GeometryError);
  });

  it.each([
    [0, 0],
    [1, 1],
    [0, 1],
    [1, 0],
  ])('угол листа допустим: (%s, %s)', (x, y) => {
    // Отвергать угол значило бы запретить обмер по краю чертежа.
    expect(() => normalizedToPdfDisplay({ x, y } as NormalizedPoint, page)).not.toThrow();
  });

  it('для длины нужно минимум две точки', () => {
    expect(() => polylineLengthPdfPoints([{ x: 0.1, y: 0.1 }] as NormalizedPoint[], page)).toThrow(
      GeometryError,
    );
  });

  it('для площади нужно минимум три точки', () => {
    expect(() =>
      polygonAreaPdfPoints2(
        [
          { x: 0.1, y: 0.1 },
          { x: 0.2, y: 0.2 },
        ] as NormalizedPoint[],
        page,
      ),
    ).toThrow(GeometryError);
  });

  it('обратное преобразование не зажимает точку в границы листа', () => {
    const result = pdfDisplayToNormalized({ x: 1500, y: -200 }, page);

    expect(result.x).toBe(1.5);
    expect(result.y).toBe(-0.2);
  });
});

describe('расстояние', () => {
  it('симметрично', () => {
    const first = { x: 10, y: 20 };
    const second = { x: 310, y: 420 };

    expect(distancePdfPoints(first, second)).toBe(distancePdfPoints(second, first));
  });

  it('на больших координатах даёт то же, что math.hypot на сервере', () => {
    // Наивный корень из суммы квадратов здесь переполняется — на сервере это проверено
    // отдельно. Значение совпадает с Python побитово, и это подтверждение ADR-0017.
    expect(distancePdfPoints({ x: 0, y: 0 }, { x: 3e200, y: 4e200 })).toBe(4.9999999999999995e200);
  });
});
