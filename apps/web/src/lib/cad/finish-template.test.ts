import { describe, expect, it } from 'vitest';

import { templateFixture } from '@/components/cad/finishes/finish-fixtures';

import {
  applyPreset,
  draftFromTemplate,
  emptyDraft,
  emptyLayer,
  isDraftValid,
  layerProblems,
  parseDecimal,
  templateProblems,
  toPatchBody,
  toWriteBody,
} from './finish-template';

const works = (layers: readonly { work: string; coats: string }[]) =>
  layers.map((layer) => `${layer.work}×${layer.coats}`);

describe('заготовки шаблона', () => {
  it('«Черновая МОП»: пол, стены, потолок; без чисел расхода и толщин', () => {
    const draft = applyPreset(emptyDraft(), 'mop-rough');
    expect(works(draft.floor)).toEqual(['Обеспыливание×1', 'Грунтовка×1', 'Стяжка×1']);
    expect(works(draft.walls)).toEqual([
      'Обеспыливание×1',
      'Грунтовка×1',
      'Штукатурка×1',
      'Шпаклёвка×1',
      'Окраска×2',
    ]);
    expect(works(draft.ceiling)).toEqual([
      'Обеспыливание×1',
      'Грунтовка×1',
      'Шпаклёвка×1',
      'Окраска×2',
    ]);
    for (const layer of [...draft.floor, ...draft.walls, ...draft.ceiling]) {
      expect(layer).toMatchObject({ material: '', thickness: '', consumption: '', unit: '' });
    }
  });

  it('основания в заготовках: обеспыливание МОП - монолит, штукатурка - монолит и кладка', () => {
    const mop = applyPreset(emptyDraft(), 'mop-rough');
    const basesOf = (layers: readonly { work: string; bases: readonly string[] }[]) =>
      Object.fromEntries(layers.map((layer) => [layer.work, layer.bases]));
    expect(basesOf(mop.walls)).toEqual({
      Обеспыливание: ['monolith'],
      Грунтовка: [],
      Штукатурка: ['monolith', 'masonry'],
      Шпаклёвка: [],
      Окраска: [],
    });
    for (const layer of [...mop.floor, ...mop.ceiling]) expect(layer.bases).toEqual([]);
    const apartment = applyPreset(emptyDraft(), 'apartment-rough');
    expect(basesOf(apartment.walls)).toEqual({
      Грунтовка: [],
      Штукатурка: ['monolith', 'masonry'],
    });
  });

  it('«Черновая квартира»', () => {
    const draft = applyPreset(emptyDraft(), 'apartment-rough');
    expect(works(draft.floor)).toEqual(['Грунтовка×1', 'Стяжка×1']);
    expect(works(draft.walls)).toEqual(['Грунтовка×1', 'Штукатурка×1']);
    expect(works(draft.ceiling)).toEqual(['Обеспыливание×1', 'Грунтовка×1']);
  });

  it('заготовка не трогает название, типы и высоту', () => {
    const base = {
      ...emptyDraft(),
      name: 'Мой',
      roomTypes: ['stair' as const],
      wallHeight: '2700',
      wallsIncludeReveals: true,
    };
    expect(applyPreset(base, 'mop-rough')).toMatchObject({
      name: 'Мой',
      roomTypes: ['stair'],
      wallHeight: '2700',
      wallsIncludeReveals: true,
    });
  });
});

describe('черновик и тело запроса', () => {
  it('числа с запятой, пустое - null', () => {
    expect(parseDecimal('0,5')).toBe(0.5);
    expect(parseDecimal(' ')).toBeNull();
    expect(parseDecimal('abc')).toBeNaN();
  });

  it('тело создания: пустые поля - null, расход на мм сохраняется', () => {
    const layer = {
      ...emptyLayer('Стяжка'),
      material: 'Смесь',
      thickness: '50',
      consumption: '1,8',
      unit: 'кг',
      perMm: true,
    };
    const body = toWriteBody({ ...emptyDraft(), name: ' Шаблон ', floor: [layer] });
    expect(body).toEqual({
      name: 'Шаблон',
      room_types: [],
      wall_height_mm: null,
      walls_include_reveals: false,
      floor_layers: [
        {
          work: 'Стяжка',
          material: 'Смесь',
          coats: 1,
          thickness_mm: 50,
          consumption: 1.8,
          consumption_unit: 'кг',
          consumption_per_mm: true,
        },
      ],
      wall_layers: [],
      ceiling_layers: [],
    });
  });

  it('основания: у слоя стен - список в каноническом порядке; ни одного или все - null; у пола нет поля', () => {
    const wall = (bases: readonly ('monolith' | 'masonry' | 'gkl')[]) => ({
      ...emptyLayer('Штукатурка', 1, bases),
    });
    const body = toWriteBody({
      ...emptyDraft(),
      name: 'А',
      wallsIncludeReveals: true,
      floor: [emptyLayer('Стяжка', 1, ['gkl'])],
      walls: [
        wall(['masonry', 'monolith']),
        wall([]),
        wall(['gkl', 'masonry', 'monolith']),
        wall(['gkl']),
      ],
    });
    expect(body.walls_include_reveals).toBe(true);
    expect(body.wall_layers?.map((layer) => layer.bases)).toEqual([
      ['monolith', 'masonry'],
      null,
      null,
      ['gkl'],
    ]);
    expect(body.floor_layers?.[0]).not.toHaveProperty('bases');
  });

  it('из шаблона: основания и флажок откосов попадают в черновик, null - все основания', () => {
    const draft = draftFromTemplate(
      templateFixture({
        walls_include_reveals: true,
        wall_layers: [
          { work: 'Штукатурка', bases: ['masonry', 'monolith'] },
          { work: 'Окраска', bases: null },
          { work: 'Грунтовка' },
        ],
      }),
    );
    expect(draft.wallsIncludeReveals).toBe(true);
    expect(draft.walls.map((layer) => layer.bases)).toEqual([['monolith', 'masonry'], [], []]);
    expect(toPatchBody(draft)).toMatchObject({ walls_include_reveals: true });
  });

  it('правка передаёт все поля, пустая высота - явный null', () => {
    const draft = {
      ...draftFromTemplate(templateFixture({ wall_height_mm: 2700 })),
      wallHeight: '',
    };
    expect(toPatchBody(draft)).toMatchObject({ wall_height_mm: null, name: 'Черновая МОП' });
  });

  it('проверка границ слоя', () => {
    expect(layerProblems({ ...emptyLayer('Работа'), coats: '6' }).coats).toBeDefined();
    expect(layerProblems({ ...emptyLayer(''), coats: '1' }).work).toBeDefined();
    expect(layerProblems({ ...emptyLayer('А'), thickness: '250' }).thickness).toBeDefined();
    expect(layerProblems({ ...emptyLayer('А'), consumption: '2' }).unit).toBeDefined();
    expect(layerProblems({ ...emptyLayer('А'), perMm: true }).thickness).toBeDefined();
    expect(layerProblems(emptyLayer('Работа'))).toEqual({});
  });

  it('проверка шаблона: название и высота 1000-6000', () => {
    expect(templateProblems(emptyDraft()).name).toBeDefined();
    expect(
      templateProblems({ ...emptyDraft(), name: 'А', wallHeight: '900' }).wallHeight,
    ).toBeDefined();
    expect(templateProblems({ ...emptyDraft(), name: 'А', wallHeight: '2700' })).toEqual({});
    expect(isDraftValid({ ...emptyDraft(), name: 'А' })).toBe(true);
  });
});
