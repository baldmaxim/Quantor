import { describe, expect, it } from 'vitest';

import { floor3dFixture, windowFixture } from './floor3d-fixtures';
import { buildFloor3dPlan, highlightListOf, highlightOf, itemAtTriangle, toScenePoint } from './floor3d-geometry';

describe('перевод координат', () => {
  const center = { x: 5000, y: 3000, z: 4000 };

  it('мм -> м, высота на оси Y, ось DXF Y идёт в -Z', () => {
    expect(toScenePoint(5000, 3000, 4000, center)).toEqual([0, 0, -0]);
    const [x, y, z] = toScenePoint(6000, 4000, 5000, center);
    expect([x, y, z]).toEqual([1, 1, -1]);
  });

  it('не зеркально: поворот на +x, +y плана сохраняет ориентацию (определитель +1)', () => {
    const o = toScenePoint(0, 0, 0, { x: 0, y: 0, z: 0 });
    const ex = toScenePoint(1000, 0, 0, { x: 0, y: 0, z: 0 });
    const ey = toScenePoint(0, 1000, 0, { x: 0, y: 0, z: 0 });
    const ez = toScenePoint(0, 0, 1000, { x: 0, y: 0, z: 0 });
    const a = ex.map((value, i) => value - (o[i] as number));
    const b = ey.map((value, i) => value - (o[i] as number));
    const c = ez.map((value, i) => value - (o[i] as number));
    const det =
      (a[0] as number) * ((b[1] as number) * (c[2] as number) - (b[2] as number) * (c[1] as number)) -
      (a[1] as number) * ((b[0] as number) * (c[2] as number) - (b[2] as number) * (c[0] as number)) +
      (a[2] as number) * ((b[0] as number) * (c[1] as number) - (b[1] as number) * (c[0] as number));
    expect(det).toBeGreaterThan(0);
  });
});

describe('план этажа', () => {
  const plan = buildFloor3dPlan(floor3dFixture());
  const find = (id: string) => plan.prisms.find((item) => item.id === id);

  it('центрируется по bbox в плане и по диапазону высот', () => {
    expect(plan.center).toEqual({ x: 5000, y: 3000, z: (2800 + 5800) / 2 });
    const slab = find('slab');
    const xs = slab?.shell.map(([u]) => u) ?? [];
    const vs = slab?.shell.map(([, v]) => v) ?? [];
    expect([Math.min(...xs), Math.max(...xs)]).toEqual([-5, 5]);
    expect([Math.min(...vs), Math.max(...vs)]).toEqual([-3, 3]);
  });

  it('высоты призм в метрах от центра: толщина плиты и высота стены сохраняются', () => {
    const slab = find('slab');
    const wall = find('w1');
    expect((slab?.yTop ?? 0) - (slab?.yBottom ?? 0)).toBeCloseTo(0.2);
    expect((wall?.yTop ?? 0) - (wall?.yBottom ?? 0)).toBeCloseTo(2.8);
    expect(slab?.yTop).toBeCloseTo(wall?.yBottom ?? NaN);
    const lintel = find('o1');
    expect((lintel?.yTop ?? 0) - (lintel?.yBottom ?? 0)).toBeCloseTo(0.7);
  });

  it('двери: призмы категории door с высотой от низа до верха полотна', () => {
    const doors = plan.prisms.filter((item) => item.category === 'door');
    expect(doors.map((item) => item.id)).toEqual(['o1', 'o2']);
    expect((doors[0]?.yTop ?? 0) - (doors[0]?.yBottom ?? 0)).toBeCloseTo(2.1);
    expect((doors[1]?.yTop ?? 0) - (doors[1]?.yBottom ?? 0)).toBeCloseTo(2.0);
  });

  it('нет поля doors - дверей нет, остальное строится', () => {
    const bare = buildFloor3dPlan(floor3dFixture({ doors: undefined }));
    expect(bare.prisms.some((item) => item.category === 'door')).toBe(false);
    expect(bare.prisms.some((item) => item.category === 'lintel')).toBe(true);
  });

  it('категории: кладка, монолит, перемычка, плита', () => {
    expect(find('w1')?.category).toBe('masonry');
    expect(find('w2')).toBeUndefined();
    expect(find('o1')?.category).toBe('lintel');
    expect(find('slab')?.category).toBe('slab');
  });

  it('стена без верхней отметки пропущена и посчитана', () => {
    expect(plan.skipped.wallsWithoutTop).toBe(1);
  });

  it('плита режется по кандидату и включённому; выключенное лежит отдельно и плиту не режет', () => {
    expect(find('slab')?.holes).toHaveLength(2);
    expect(plan.holes.map((hole) => [hole.key, hole.state])).toEqual([
      ['h1', 'candidate'],
      ['h2', 'enabled'],
    ]);
    expect(plan.disabledHoles.map((hole) => [hole.key, hole.state])).toEqual([['h3', 'disabled']]);
    expect(plan.disabledHoles[0]?.y).toBeCloseTo(find('slab')?.yTop ?? NaN);
    expect(plan.holes[0]?.y).toBeCloseTo(find('slab')?.yTop ?? NaN);
  });

  it('«Плита сверху»: копия плиты на верхе стен той же толщины', () => {
    const cap = plan.slabCap;
    expect(cap).not.toBeNull();
    expect(cap?.yBottom).toBeCloseTo(find('w1')?.yTop ?? NaN);
    expect((cap?.yTop ?? 0) - (cap?.yBottom ?? 0)).toBeCloseTo(0.2);
  });

  it('габарит модели в метрах', () => {
    expect(plan.extent.width).toBe(10);
    expect(plan.extent.depth).toBe(6);
    expect(plan.extent.height).toBeCloseTo(3.0);
  });

  it('без bbox сервера центр берётся по контурам', () => {
    const noBbox = buildFloor3dPlan(floor3dFixture({ bbox: null }));
    expect(noBbox.center.x).toBe(5000);
    expect(noBbox.center.y).toBe(3000);
  });

  it('замыкающая точка-повтор контура убирается; контур из двух точек не строится', () => {
    const model = floor3dFixture({
      slab: {
        shell: [
          [0, 0],
          [1000, 0],
          [1000, 1000],
          [0, 0],
        ],
        z_bottom_mm: 0,
        z_top_mm: 200,
        area_m2: 0.5,
      },
      walls: [
        {
          ...floor3dFixture().walls[0]!,
          shell: [
            [0, 0],
            [1, 1],
          ],
        },
      ],
    });
    const result = buildFloor3dPlan(model);
    expect(result.prisms.find((item) => item.id === 'slab')?.shell).toHaveLength(3);
    expect(result.skipped.degenerate).toBeGreaterThan(0);
  });

  it('плита без низа (нет толщины) не строится, это отмечено', () => {
    const model = floor3dFixture();
    const result = buildFloor3dPlan({
      ...model,
      slab: model.slab && { ...model.slab, z_bottom_mm: null },
    });
    expect(result.skipped.slabWithoutBottom).toBe(true);
    expect(result.prisms.find((item) => item.category === 'slab')).toBeUndefined();
    expect(result.holes).toEqual([]);
    expect(result.disabledHoles).toEqual([]);
  });

  it('пустая модель - пустой план', () => {
    const empty = buildFloor3dPlan(
      floor3dFixture({ slab: null, slab_holes: [], walls: [], lintels: [], doors: [], bbox: null }),
    );
    expect(empty.prisms).toEqual([]);
    expect(empty.extent).toEqual({ width: 0, height: 0, depth: 0 });
  });
});

describe('треугольник -> элемент', () => {
  it('бинарный поиск по началам диапазонов', () => {
    const starts = [0, 12, 30];
    expect(itemAtTriangle(starts, 40, 0)).toBe(0);
    expect(itemAtTriangle(starts, 40, 11)).toBe(0);
    expect(itemAtTriangle(starts, 40, 12)).toBe(1);
    expect(itemAtTriangle(starts, 40, 29)).toBe(1);
    expect(itemAtTriangle(starts, 40, 39)).toBe(2);
    expect(itemAtTriangle(starts, 40, 40)).toBe(-1);
    expect(itemAtTriangle(starts, 40, -1)).toBe(-1);
    expect(itemAtTriangle([], 0, 0)).toBe(-1);
  });
});

describe('план оверлея выделения', () => {
  const plan = buildFloor3dPlan(floor3dFixture());

  it('стена - призма из плана с теми же высотами', () => {
    const target = highlightOf(plan, { kind: 'prism', category: 'masonry', id: 'w1' });
    expect(target?.kind).toBe('prism');
    expect(target?.kind === 'prism' && target.spec.id).toBe('w1');
    expect(target?.kind === 'prism' && target.spec.yTop).toBeCloseTo(1.5, 6);
  });

  it('перемычка - призма категории lintel', () => {
    const target = highlightOf(plan, { kind: 'prism', category: 'lintel', id: 'o1' });
    expect(target?.kind === 'prism' && target.spec.category).toBe('lintel');
  });

  it('дверь - призма категории door', () => {
    const target = highlightOf(plan, { kind: 'prism', category: 'door', id: 'o2' });
    expect(target?.kind === 'prism' && target.spec.category).toBe('door');
    expect(highlightOf(plan, { kind: 'prism', category: 'door', id: 'w1' })).toBeNull();
  });

  it('отверстие - любое состояние, включая «Не отверстие»', () => {
    for (const key of ['h1', 'h2', 'h3']) {
      const target = highlightOf(plan, { kind: 'hole', category: 'hole', id: key });
      expect(target?.kind === 'hole' && target.spec.key).toBe(key);
    }
  });

  it('нет выбора, нет в плане (стена без высоты), чужая категория - null', () => {
    expect(highlightOf(plan, null)).toBeNull();
    expect(highlightOf(plan, { kind: 'prism', category: 'monolith', id: 'w2' })).toBeNull();
    expect(highlightOf(plan, { kind: 'prism', category: 'lintel', id: 'w1' })).toBeNull();
  });
});

describe('окна по фасаду', () => {
  it('подоконная часть и стекло с нужными высотами, в метрах от центра', () => {
    const plan = buildFloor3dPlan(floor3dFixture({ windows: [windowFixture()] }));
    const sill = plan.prisms.find((item) => item.category === 'sill')!;
    const glass = plan.prisms.find((item) => item.category === 'glass')!;
    expect(sill.yTop - sill.yBottom).toBeCloseTo(0.9);
    expect(glass.yTop - glass.yBottom).toBeCloseTo(1.1);
    expect(glass.yBottom).toBeCloseTo(sill.yTop);
    expect(glass.accepted).toBe(true);
    expect(sill.hostId).toBe('w1');
  });

  it('окно по ручному вводу строится как принятое: тот же признак, что у принятого по фасаду', () => {
    const plan = buildFloor3dPlan(
      floor3dFixture({
        windows: [
          windowFixture({ source: 'manual', facade_view_key: null, facade_title: null }),
          windowFixture({ opening_id: 'win2', accepted: false }),
        ],
      }),
    );
    const accepted = (id: string) =>
      plan.prisms.filter((item) => item.id === id).map((item) => item.accepted);
    expect(accepted('win1')).toEqual([true, true]);
    // кандидат отличается от ручного ввода
    expect(accepted('win2')).toEqual([false, false]);
  });

  it('низ стекла равен низу окна - подоконной части нет', () => {
    const plan = buildFloor3dPlan(
      floor3dFixture({ windows: [windowFixture({ sill_z_top_mm: 3000, accepted: false })] }),
    );
    expect(plan.prisms.some((item) => item.category === 'sill')).toBe(false);
    expect(plan.prisms.find((item) => item.category === 'glass')?.accepted).toBe(false);
  });

  it('нет поля windows - окон нет; выбор окна подсвечивает обе части', () => {
    expect(
      buildFloor3dPlan(floor3dFixture({ windows: undefined })).prisms.some((i) => i.category === 'glass'),
    ).toBe(false);
    const plan = buildFloor3dPlan(floor3dFixture({ windows: [windowFixture()] }));
    const list = highlightListOf(plan, { kind: 'prism', category: 'glass', id: 'win1' });
    expect(list.map((item) => (item.kind === 'prism' ? item.spec.category : '')).sort()).toEqual([
      'glass',
      'sill',
    ]);
  });
});

describe('плита из нескольких частей', () => {
  const rect = (x0: number, y0: number, x1: number, y1: number): number[][] => [
    [x0, y0],
    [x1, y0],
    [x1, y1],
    [x0, y1],
  ];
  const main = rect(0, 0, 10000, 6000);
  const second = rect(14000, 0, 16000, 3000);
  const holes = [
    { key: 'a', shell: rect(1000, 1000, 2000, 2000), area_m2: 1, state: 'enabled' as const },
    { key: 'b', shell: rect(14500, 500, 15000, 1000), area_m2: 0.25, state: 'enabled' as const },
    { key: 'c', shell: rect(11000, 1000, 12000, 2000), area_m2: 1, state: 'enabled' as const },
  ];
  const multi = floor3dFixture({
    bbox: [0, 0, 16000, 6000],
    slab: {
      shell: main,
      parts: [main, second],
      z_bottom_mm: 2800,
      z_top_mm: 3000,
      area_m2: 66,
    },
    slab_holes: holes,
  });

  it('обе части - одна призма плиты; отверстия вычитаются из той части, куда попадают', () => {
    const plan = buildFloor3dPlan(multi);
    const slabs = plan.prisms.filter((item) => item.category === 'slab');
    expect(slabs).toHaveLength(1);
    const [slab] = slabs;
    expect(slab?.holes).toHaveLength(1);
    expect(slab?.extraParts).toHaveLength(1);
    expect(slab?.extraParts?.[0]?.holes).toHaveLength(1);
    // Отверстие вне обеих частей не вычитается, но остаётся в списке отверстий плана.
    expect(plan.holes.map((hole) => hole.key)).toEqual(['a', 'b', 'c']);
    const xs = (slab?.extraParts?.[0]?.shell ?? []).map(([u]) => u);
    expect(plan.center.x).toBe(8000);
    expect(Math.max(...xs)).toBeCloseTo(8);
    expect(plan.slabCap?.extraParts).toHaveLength(1);
  });

  it('без parts - плита как раньше: одна часть, все отверстия в ней', () => {
    const plan = buildFloor3dPlan(floor3dFixture());
    const slab = plan.prisms.find((item) => item.category === 'slab');
    expect(slab?.extraParts).toBeUndefined();
    expect(slab?.holes).toHaveLength(2);
  });

  it('parts из одной основной части не создаёт лишних частей', () => {
    const plan = buildFloor3dPlan(
      floor3dFixture({ slab: { shell: main, parts: [main], z_bottom_mm: 2800, z_top_mm: 3000, area_m2: 60 } }),
    );
    expect(plan.prisms.find((item) => item.category === 'slab')?.extraParts).toBeUndefined();
  });
});
