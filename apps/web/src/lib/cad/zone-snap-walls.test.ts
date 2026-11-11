import type { CadPreviewPathRead, CadPreviewRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import type { ICadFrame, IPageSize } from './frame';
import { buildSnapIndex, snapPoint } from './zone-snap';
import { buildWallSnapIndex, isWallSnapLayer, wallSnapShapes } from './zone-snap-walls';

// 1 pt = 10 мм, начало DXF на странице в (100, 200) pt; страница 1000 x 500 pt.
const FRAME: ICadFrame = { originX: 100, originY: 200, mmPerPt: 10 };
const PAGE: IPageSize = { width: 1000, height: 500 };

const preview = (layers: string[], paths: CadPreviewPathRead[]): CadPreviewRead =>
  ({ layers, paths }) as unknown as CadPreviewRead;

const rect = (
  layer: number,
  x0: number,
  y0: number,
  x1: number,
  y1: number,
): CadPreviewPathRead => ({
  closed: true,
  fill: false,
  layer,
  points: [x0, y0, x1, y0, x1, y1, x0, y1],
});

describe('isWallSnapLayer', () => {
  it('контуры стен и монолит - да, QA и прочее - нет', () => {
    expect(isWallSnapLayer('01_КОНТУРЫ_СТЕН')).toBe(true);
    expect(isWallSnapLayer('02_МОНОЛИТ')).toBe(true);
    expect(isWallSnapLayer('02_МОНОЛИТ_КАНДИДАТЫ')).toBe(true);
    expect(isWallSnapLayer('QA_01_КОНТУРЫ_СТЕН')).toBe(false);
    expect(isWallSnapLayer('qa_02_МОНОЛИТ')).toBe(false);
    expect(isWallSnapLayer('01_СТЕНЫ_КАНДИДАТЫ')).toBe(false);
    expect(isWallSnapLayer('11_ТЕКСТ_И_МАРКИ')).toBe(false);
  });
});

describe('wallSnapShapes', () => {
  it('переводит мм DXF в доли листа тем же кадром, что и наложение (с переворотом Y)', () => {
    // Точка DXF (1000, 500) мм -> pt (100 + 100, 200 - 50) = (200, 150) -> (0.2, 0.3).
    const shapes = wallSnapShapes(
      preview(['01_КОНТУРЫ_СТЕН'], [rect(0, 1000, 500, 2000, 1000)]),
      FRAME,
      PAGE,
    );
    expect(shapes).toHaveLength(1);
    const points = shapes[0]?.points ?? [];
    expect(points[0]?.[0]).toBeCloseTo(0.2, 10);
    expect(points[0]?.[1]).toBeCloseTo(0.3, 10);
    // (2000, 1000) мм -> pt (300, 100) -> (0.3, 0.2): больший Y DXF - выше на листе.
    expect(points[2]?.[0]).toBeCloseTo(0.3, 10);
    expect(points[2]?.[1]).toBeCloseTo(0.2, 10);
    expect(shapes[0]?.closed).toBe(true);
  });

  it('слои сопоставляются по имени, а не по номеру; QA и прочие слои пропускаются', () => {
    const shapes = wallSnapShapes(
      preview(
        ['11_ТЕКСТ_И_МАРКИ', 'QA_01_КОНТУРЫ_СТЕН', '02_МОНОЛИТ_КАНДИДАТЫ', '01_КОНТУРЫ_СТЕН'],
        [
          rect(0, 0, 0, 100, 100),
          rect(1, 0, 0, 100, 100),
          rect(2, 0, 0, 200, 200),
          rect(3, 0, 0, 300, 300),
        ],
      ),
      FRAME,
      PAGE,
    );
    expect(shapes).toHaveLength(2);
  });

  it('вырожденные пути (меньше двух точек) пропускаются', () => {
    const shapes = wallSnapShapes(
      preview(['01_КОНТУРЫ_СТЕН'], [{ closed: false, fill: false, layer: 0, points: [1, 2] }]),
      FRAME,
      PAGE,
    );
    expect(shapes).toEqual([]);
  });
});

describe('buildWallSnapIndex', () => {
  it('нет предпросмотра, кадра, страницы или слоёв стен - null', () => {
    const walls = preview(['01_КОНТУРЫ_СТЕН'], [rect(0, 0, 0, 100, 100)]);
    expect(buildWallSnapIndex(null, FRAME, PAGE)).toBeNull();
    expect(buildWallSnapIndex(walls, null, PAGE)).toBeNull();
    expect(buildWallSnapIndex(walls, FRAME, null)).toBeNull();
    expect(
      buildWallSnapIndex(preview(['10_ШТРИХОВКИ'], [rect(0, 0, 0, 1, 1)]), FRAME, PAGE),
    ).toBeNull();
  });

  it('индекс на 30 000 точек строится быстро', () => {
    const paths: CadPreviewPathRead[] = [];
    for (let at = 0; at < 1000; at += 1) {
      const points: number[] = [];
      for (let k = 0; k < 30; k += 1) {
        points.push(((at * 37 + k * 11) % 5000) * 3, ((at * 53 + k * 7) % 3000) * 3);
      }
      paths.push({ closed: true, fill: false, layer: 0, points });
    }
    const big = preview(['01_КОНТУРЫ_СТЕН'], paths);
    const started = performance.now();
    const index = buildWallSnapIndex(big, FRAME, PAGE);
    const elapsed = performance.now() - started;
    console.info(`wall snap index, 30000 points: ${elapsed.toFixed(1)} ms`);
    expect(index?.vertices).toHaveLength(30000);
    expect(elapsed).toBeLessThan(1000);
  });
});

describe('привязка к стенам', () => {
  // Стена: прямоугольник (1000,500)-(2000,1000) мм -> доли (0.2, 0.3)-(0.3, 0.2).
  const walls = buildWallSnapIndex(
    preview(['01_КОНТУРЫ_СТЕН'], [rect(0, 1000, 500, 2000, 1000)]),
    FRAME,
    PAGE,
  );
  const scale = { x: 1000, y: 500 };
  const base = { scale, placed: [], shift: false, alt: false };

  it('угол стены в радиусе: kind corner в точке угла', () => {
    const result = snapPoint({ x: 0.204, y: 0.302 }, { ...base, index: buildSnapIndex([]), walls });
    expect(result.kind).toBe('corner');
    expect(result.point.x).toBeCloseTo(0.2, 10);
    expect(result.point.y).toBeCloseTo(0.3, 10);
  });

  it('грань стены в радиусе: точка на грани', () => {
    // Верхняя грань y = 0.2 между x 0.2..0.3.
    const result = snapPoint({ x: 0.25, y: 0.202 }, { ...base, index: buildSnapIndex([]), walls });
    expect(result.kind).toBe('edge');
    expect(result.point.x).toBeCloseTo(0.25, 10);
    expect(result.point.y).toBeCloseTo(0.2, 10);
  });

  it('приоритет: угол стены > вершина зоны > грань стены > ребро зоны', () => {
    const zone = {
      closed: true,
      points: [
        [0.2, 0.3],
        [0.2, 0.31],
        [0.19, 0.31],
      ] as [number, number][],
    };
    const index = buildSnapIndex([zone]);
    // Курсор в 5 px от угла стены (0.2, 0.3) и в 0 px от вершины зоны (0.2, 0.31): угол выигрывает.
    const near = { x: 0.2, y: 0.3 + 5 / 500 };
    expect(snapPoint(near, { ...base, index, walls }).kind).toBe('corner');
    // Без стен то же место даёт вершину зоны.
    expect(snapPoint(near, { ...base, index, walls: null }).kind).toBe('vertex');

    // Вершина зоны на 4 px от курсора, грань стены - на 1 px: вершина выигрывает.
    const vertexOnly = buildSnapIndex([
      {
        closed: false,
        points: [
          [0.25, 0.2 + 4 / 500],
          [0.25, 0.5],
        ],
      },
    ]);
    const onVertex = snapPoint(
      { x: 0.25, y: 0.2 + 1 / 500 },
      { ...base, index: vertexOnly, walls },
    );
    expect(onVertex.kind).toBe('vertex');

    // Ребро зоны ближе (1 px), грань стены дальше (4 px): грань стены выигрывает.
    const edgeZone = buildSnapIndex([
      {
        closed: false,
        points: [
          [0.22, 0.2 + 5 / 500],
          [0.28, 0.2 + 5 / 500],
        ],
      },
    ]);
    const onWall = snapPoint({ x: 0.25, y: 0.2 + 4 / 500 }, { ...base, index: edgeZone, walls });
    expect(onWall.kind).toBe('edge');
    expect(onWall.point.y).toBeCloseTo(0.2, 10);
  });

  it('вне радиуса привязки нет; Alt её отключает', () => {
    const empty = buildSnapIndex([]);
    expect(snapPoint({ x: 0.25, y: 0.25 }, { ...base, index: empty, walls }).kind).toBe('none');
    expect(
      snapPoint({ x: 0.204, y: 0.302 }, { ...base, index: empty, walls, alt: true }).kind,
    ).toBe('none');
  });

  it('Shift: ortho-проекция попадает в угол стены', () => {
    // Опорная (0.1, 0.3); курсор (0.2, 0.31): горизонталь y = 0.3 -> угол (0.2, 0.3).
    const result = snapPoint(
      { x: 0.2, y: 0.31 },
      { ...base, index: buildSnapIndex([]), walls, placed: [{ x: 0.1, y: 0.3 }], shift: true },
    );
    expect(result.kind).toBe('corner');
    expect(result.point.x).toBeCloseTo(0.2, 10);
  });

  it('Shift: ось пересекает грань стены - точка пересечения', () => {
    // Опорная (0.1, 0.25); горизонталь y = 0.25 пересекает левую грань x = 0.2.
    const result = snapPoint(
      { x: 0.2 + 4 / 1000, y: 0.26 },
      { ...base, index: buildSnapIndex([]), walls, placed: [{ x: 0.1, y: 0.25 }], shift: true },
    );
    expect(result.kind).toBe('edge');
    expect(result.point.x).toBeCloseTo(0.2, 10);
    expect(result.point.y).toBeCloseTo(0.25, 10);
  });

  it('без индекса стен работает как раньше', () => {
    const result = snapPoint({ x: 0.204, y: 0.302 }, { ...base, index: buildSnapIndex([]) });
    expect(result.kind).toBe('none');
  });
});
