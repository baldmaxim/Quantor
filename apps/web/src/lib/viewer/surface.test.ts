import { describe, expect, it } from 'vitest';

import {
  FULL_PAGE_MAX_PIXELS,
  fullPageScaleLimit,
  pieceStyle,
  planRaster,
  planStillValid,
  samePlan,
  stackTransform,
  surfaceCovers,
  surfaceRegionFor,
  visiblePageRect,
  type RasterPiece,
} from './surface';

/**
 * Растр листа по видимой части (ADR-0025).
 *
 * Ошибки этого модуля видны на экране как белые полосы у края листа при панораме, шов между
 * резкой частью и подложкой или лишняя отрисовка pdf.js на каждой паузе жеста. Поэтому
 * проверяются границы, выравнивание по пикселям и решение «рисовать или нет».
 */

// Эталонный лист A1 после /Rotate 90 — то, что отдаёт pdf.js.
const PAGE = { width: 2384, height: 1684 };
const VIEWPORT = { width: 1600, height: 1000 };

/** Камера, при которой центр листа в центре области. */
const centered = (scale: number, shiftX = 0, shiftY = 0) => ({
  scale,
  offsetX: VIEWPORT.width / 2 - (PAGE.width * scale) / 2 + shiftX,
  offsetY: VIEWPORT.height / 2 - (PAGE.height * scale) / 2 + shiftY,
});

describe('видимая часть листа', () => {
  it('левый верхний угол области — минус смещение камеры в единицах листа', () => {
    expect(
      visiblePageRect({ scale: 2, offsetX: -1000, offsetY: -500 }, { width: 800, height: 600 }),
    ).toEqual({ x: 500, y: 250, width: 400, height: 300 });
  });
});

describe('предел пикселей растра во весь лист', () => {
  it('лист в масштабе предела укладывается в предел', () => {
    for (const ratio of [1, 1.5, 2]) {
      const scale = fullPageScaleLimit(PAGE, ratio);
      const pixels =
        Math.floor(PAGE.width * scale * ratio) * Math.floor(PAGE.height * scale * ratio);
      expect(pixels).toBeLessThanOrEqual(FULL_PAGE_MAX_PIXELS);
      expect(pixels).toBeGreaterThan(FULL_PAGE_MAX_PIXELS * 0.99);
    }
  });

  it('A1 при 100 % на плотности 1,5 — ещё один растр', () => {
    expect(fullPageScaleLimit(PAGE, 1.5)).toBeGreaterThan(1);
  });
});

describe('резкая часть', () => {
  it('без раскладки области рисовать нечего', () => {
    expect(surfaceRegionFor(PAGE, centered(2.66), { width: 0, height: 0 }, 1.5)).toBeNull();
  });

  it('лист целиком за краем области — рисовать нечего', () => {
    expect(
      surfaceRegionFor(PAGE, { scale: 2.66, offsetX: 50_000, offsetY: 0 }, VIEWPORT, 1.5),
    ).toBeNull();
  });

  it('видимая область с полями в половину области с каждой стороны', () => {
    const region = surfaceRegionFor(PAGE, centered(2.66), VIEWPORT, 1.5);
    if (!region) throw new Error('резкая часть не построена');

    // Вдвое больше области по каждой оси — с точностью до выравнивания по пикселям.
    expect(region.width * 2.66).toBeGreaterThanOrEqual(VIEWPORT.width * 2);
    expect(region.width * 2.66).toBeLessThanOrEqual(VIEWPORT.width * 2 + 2 / 1.5);
    expect(region.height * 2.66).toBeGreaterThanOrEqual(VIEWPORT.height * 2);
    expect(region.scale).toBe(2.66);
    // Растр части не зависит от масштаба: четыре области в физических пикселях, а не лист.
    const pixels = region.width * 2.66 * 1.5 * (region.height * 2.66 * 1.5);
    expect(pixels).toBeLessThan((VIEWPORT.width * 2 * 1.5 + 2) * (VIEWPORT.height * 2 * 1.5 + 2));
  });

  it('края части лежат на границах физических пикселей листа', () => {
    const region = surfaceRegionFor(PAGE, centered(2.66, 12.345, -6.789), VIEWPORT, 1.5);
    if (!region) throw new Error('резкая часть не построена');
    const density = 2.66 * 1.5;

    for (const edge of [region.x, region.y, region.x + region.width, region.y + region.height]) {
      const pixels = edge * density;
      expect(Math.abs(pixels - Math.round(pixels))).toBeLessThan(1e-6);
    }
  });

  it('у края листа часть обрезана листом, а правый край — та же формула, что у листа целиком', () => {
    const scale = 2.66;
    const ratio = 1.5;
    // Правый нижний угол листа в правом нижнем углу области.
    const camera = {
      scale,
      offsetX: VIEWPORT.width - PAGE.width * scale,
      offsetY: VIEWPORT.height - PAGE.height * scale,
    };
    const region = surfaceRegionFor(PAGE, camera, VIEWPORT, ratio);
    if (!region) throw new Error('резкая часть не построена');

    const density = scale * ratio;
    expect((region.x + region.width) * density).toBeCloseTo(Math.floor(PAGE.width * density), 6);
    expect((region.y + region.height) * density).toBeCloseTo(Math.floor(PAGE.height * density), 6);
  });
});

describe('покрытие вида', () => {
  it('часть покрывает вид, для которого построена, и панораму в пределах полей', () => {
    const region = surfaceRegionFor(PAGE, centered(2.66), VIEWPORT, 1.5);
    if (!region) throw new Error('резкая часть не построена');

    expect(surfaceCovers(region, PAGE, centered(2.66), VIEWPORT, 1.5)).toBe(true);
    expect(surfaceCovers(region, PAGE, centered(2.66, 790, -490), VIEWPORT, 1.5)).toBe(true);
  });

  it('панорама за поля — часть больше не покрывает вид', () => {
    const region = surfaceRegionFor(PAGE, centered(2.66), VIEWPORT, 1.5);
    if (!region) throw new Error('резкая часть не построена');

    expect(surfaceCovers(region, PAGE, centered(2.66, 810, 0), VIEWPORT, 1.5)).toBe(false);
    expect(surfaceCovers(region, PAGE, centered(2.66, 0, -510), VIEWPORT, 1.5)).toBe(false);
  });

  it('лист, ушедший за край области, «покрыт»: рисовать нечего', () => {
    const region = { x: 0, y: 0, width: 10, height: 10, scale: 2.66 };
    expect(
      surfaceCovers(region, PAGE, { scale: 2.66, offsetX: 50_000, offsetY: 0 }, VIEWPORT, 1.5),
    ).toBe(true);
  });

  it('у правого края листа часть покрывает вид, для которого построена', () => {
    // Регрессия-ловушка: лист шириной 2384 pt при плотности 3,99 — это 9512,16 пикселя, растр
    // рисует 9512. Сравни покрытие с дробным краем листа — часть у края «не покрывала» бы
    // последнюю долю пикселя и перерисовывалась бы после каждой отрисовки без конца.
    for (const scale of [2.66, 3.1415, 4.2]) {
      const camera = {
        scale,
        offsetX: VIEWPORT.width - PAGE.width * scale + 37.5,
        offsetY: VIEWPORT.height - PAGE.height * scale + 11.25,
      };
      const region = surfaceRegionFor(PAGE, camera, VIEWPORT, 1.5);
      if (!region) throw new Error('резкая часть не построена');
      expect(surfaceCovers(region, PAGE, camera, VIEWPORT, 1.5)).toBe(true);
      expect(
        planRaster({ base: null, detail: { region, ratio: 1.5 } }, PAGE, camera, VIEWPORT, 1.5)
          ?.kind,
      ).not.toBe('detail');
    }
  });
});

describe('план отрисовки', () => {
  const RATIO = 1.5;
  const limit = fullPageScaleLimit(PAGE, RATIO);
  const whole = (scale: number): RasterPiece => ({
    region: { x: 0, y: 0, width: PAGE.width, height: PAGE.height, scale },
    ratio: RATIO,
  });

  it('в пределе пикселей — весь лист в масштабе камеры', () => {
    const plan = planRaster({ base: null, detail: null }, PAGE, centered(1), VIEWPORT, RATIO);

    expect(plan).toEqual({ kind: 'page', region: whole(1).region, ratio: RATIO });
  });

  it('лист уже в этом масштабе — pdf.js не нужен', () => {
    expect(
      planRaster({ base: whole(1), detail: null }, PAGE, centered(1, 300, -200), VIEWPORT, RATIO),
    ).toBeNull();
  });

  it('другая плотность экрана — лист перерисовывается', () => {
    // 80 % укладывается в предел и на плотности 2: сменилась только плотность.
    expect(
      planRaster({ base: whole(0.8), detail: null }, PAGE, centered(0.8), VIEWPORT, 2),
    ).toEqual({ kind: 'page', region: whole(0.8).region, ratio: 2 });
  });

  it('выше предела сначала резкая часть — даже когда подложки нет', () => {
    const plan = planRaster(
      { base: whole(0.6), detail: null },
      PAGE,
      centered(2.66),
      VIEWPORT,
      RATIO,
    );

    expect(plan?.kind).toBe('detail');
    expect(plan?.region.scale).toBe(2.66);
  });

  it('после резкой части — подложка, если прежний лист слишком груб', () => {
    const detail = planRaster({ base: null, detail: null }, PAGE, centered(2.66), VIEWPORT, RATIO);
    if (detail?.kind !== 'detail') throw new Error('ожидалась резкая часть');

    const plan = planRaster(
      { base: whole(0.6), detail: { region: detail.region, ratio: RATIO } },
      PAGE,
      centered(2.66),
      VIEWPORT,
      RATIO,
    );

    expect(plan).toEqual({ kind: 'backdrop', region: whole(limit).region, ratio: RATIO });
  });

  it('лист немного грубее предела служит подложкой без перерисовки', () => {
    const detail = planRaster({ base: null, detail: null }, PAGE, centered(2.66), VIEWPORT, RATIO);
    if (detail?.kind !== 'detail') throw new Error('ожидалась резкая часть');

    expect(
      planRaster(
        { base: whole(limit * 0.8), detail: { region: detail.region, ratio: RATIO } },
        PAGE,
        centered(2.66),
        VIEWPORT,
        RATIO,
      ),
    ).toBeNull();
  });

  it('панорама в пределах полей не требует ничего, за полями — новую резкую часть', () => {
    const detail = planRaster({ base: null, detail: null }, PAGE, centered(2.66), VIEWPORT, RATIO);
    if (detail?.kind !== 'detail') throw new Error('ожидалась резкая часть');
    const pieces = { base: whole(limit), detail: { region: detail.region, ratio: RATIO } };

    expect(planRaster(pieces, PAGE, centered(2.66, 700, 400), VIEWPORT, RATIO)).toBeNull();
    expect(planRaster(pieces, PAGE, centered(2.66, 900, 0), VIEWPORT, RATIO)?.kind).toBe('detail');
  });

  it('зум выше предела — новая резкая часть в новом масштабе', () => {
    const detail = planRaster({ base: null, detail: null }, PAGE, centered(2.66), VIEWPORT, RATIO);
    if (detail?.kind !== 'detail') throw new Error('ожидалась резкая часть');
    const pieces = { base: whole(limit), detail: { region: detail.region, ratio: RATIO } };

    const plan = planRaster(pieces, PAGE, centered(4), VIEWPORT, RATIO);
    expect(plan?.kind).toBe('detail');
    expect(plan?.region.scale).toBe(4);
  });

  it('зум обратно в предел — весь лист, резкая часть больше не нужна', () => {
    const detail = planRaster({ base: null, detail: null }, PAGE, centered(2.66), VIEWPORT, RATIO);
    if (detail?.kind !== 'detail') throw new Error('ожидалась резкая часть');
    const pieces = { base: whole(limit), detail: { region: detail.region, ratio: RATIO } };

    expect(planRaster(pieces, PAGE, centered(1), VIEWPORT, RATIO)).toEqual({
      kind: 'page',
      region: whole(1).region,
      ratio: RATIO,
    });
  });

  it('без раскладки области выше предела рисуется только подложка', () => {
    expect(
      planRaster({ base: null, detail: null }, PAGE, centered(2.66), { width: 0, height: 0 }, RATIO)
        ?.kind,
    ).toBe('backdrop');
  });

  it('резкая часть во весь лист — подложке нечего закрывать', () => {
    // Огромный экран: область вдвое больше листа при масштабе чуть выше предела.
    const huge = { width: 20_000, height: 20_000 };
    const camera = { scale: limit * 1.1, offsetX: 0, offsetY: 0 };
    const region = surfaceRegionFor(PAGE, camera, huge, RATIO);
    if (!region) throw new Error('резкая часть не построена');

    expect(
      planRaster({ base: null, detail: { region, ratio: RATIO } }, PAGE, camera, huge, RATIO),
    ).toBeNull();
  });
});

describe('идущая отрисовка', () => {
  const RATIO = 1.5;

  it('резкая часть, всё ещё покрывающая вид, не обрывается', () => {
    const running = planRaster({ base: null, detail: null }, PAGE, centered(2.66), VIEWPORT, RATIO);
    const next = planRaster(
      { base: null, detail: null },
      PAGE,
      centered(2.66, 300, 0),
      VIEWPORT,
      RATIO,
    );
    if (!running || !next) throw new Error('планы не построены');

    expect(planStillValid(running, next, PAGE, centered(2.66, 300, 0), VIEWPORT)).toBe(true);
    expect(planStillValid(running, next, PAGE, centered(2.66, 900, 0), VIEWPORT)).toBe(false);
  });

  it('другой вид отрисовки или другая плотность — обрывается', () => {
    const detail = planRaster({ base: null, detail: null }, PAGE, centered(2.66), VIEWPORT, RATIO);
    const page = planRaster({ base: null, detail: null }, PAGE, centered(1), VIEWPORT, RATIO);
    if (!detail || !page) throw new Error('планы не построены');

    expect(planStillValid(detail, page, PAGE, centered(1), VIEWPORT)).toBe(false);
    expect(planStillValid(page, { ...page, ratio: 2 }, PAGE, centered(1), VIEWPORT)).toBe(false);
    expect(planStillValid(page, page, PAGE, centered(1), VIEWPORT)).toBe(true);
  });

  it('тот же растр узнаётся до бита, соседний — нет', () => {
    const plan = planRaster({ base: null, detail: null }, PAGE, centered(2.66), VIEWPORT, RATIO);
    const moved = planRaster(
      { base: null, detail: null },
      PAGE,
      centered(2.66, 900, 0),
      VIEWPORT,
      RATIO,
    );
    if (!plan || !moved) throw new Error('планы не построены');

    expect(samePlan(plan, { ...plan, region: { ...plan.region } })).toBe(true);
    expect(samePlan(plan, moved)).toBe(false);
  });
});

describe('размещение в стопке', () => {
  it('растр занимает свой прямоугольник листа в масштабе раскладки', () => {
    expect(pieceStyle({ x: 100, y: 50, width: 600, height: 400 }, 2)).toEqual({
      left: '200px',
      top: '100px',
      width: '1200px',
      height: '800px',
    });
  });

  it('стопка сдвигается камерой и растягивается отношением масштабов', () => {
    expect(stackTransform(2, { scale: 3, offsetX: -10.5, offsetY: 20 })).toBe(
      'translate(-10.5px, 20px) scale(1.5)',
    );
  });
});
