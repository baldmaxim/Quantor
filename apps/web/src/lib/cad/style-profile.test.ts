import { describe, expect, it } from 'vitest';

import {
  MAX_STYLE_SAMPLES,
  addStyleSample,
  areaText,
  parseStylePreview,
  profileSourceText,
  removeStyleSample,
  sampleOrdinal,
  shareText,
  type StyleSample,
} from './style-profile';

const sample = (over: Partial<StyleSample> = {}): StyleSample => ({
  class: 'monolith',
  x: 0.5,
  y: 0.5,
  negative: false,
  ...over,
});

const goodPreview = {
  schema: 'cad_engine.style_preview.v1',
  classes: {
    monolith: { grays: [0.5], fills: 12, area_pt2: 100, area_m2: null },
    shaft: { grays: [0.7], fills: 3, area_pt2: 20, area_m2: 1.5 },
    masonry: { grays: [0.3], hatch_segments: 40 },
    door: { pen_max_width: 0.35, candidates_not_doors: 7 },
  },
  field_sources: { monolith_fill_gray: 'samples', shaft_fill_gray: 'base:default' },
  unclassified_fill_share: null,
  rejected_samples: [
    { sample: { index: 1, class: 'door', x: 0.1, y: 0.2, negative: false }, reason: 'no_arc_at_point' },
  ],
  unsupported_samples: [],
  warnings: [{ code: 'conflict', message: 'Серый совпал', klass: 'monolith' }],
};

describe('образцы профиля', () => {
  it('добавляет и удаляет, не меняя исходный список', () => {
    const one = addStyleSample([], sample());
    const two = addStyleSample(one, sample({ class: 'door', negative: true }));
    expect(one).toHaveLength(1);
    expect(two).toHaveLength(2);
    expect(removeStyleSample(two, 0)).toEqual([two[1]]);
  });

  it('предел 200: лишний образец не добавляется', () => {
    let list: readonly StyleSample[] = [];
    for (let i = 0; i < MAX_STYLE_SAMPLES; i += 1) {
      list = addStyleSample(list, sample({ x: i / 1000 }));
    }
    expect(list).toHaveLength(200);
    expect(addStyleSample(list, sample())).toBe(list);
  });

  it('отрицательный образец сохраняет признак, номер считается по классу', () => {
    const list = [sample(), sample({ class: 'door' }), sample({ negative: true })];
    expect(list[2]?.negative).toBe(true);
    expect(sampleOrdinal(list, 0)).toBe(1);
    expect(sampleOrdinal(list, 1)).toBe(1);
    expect(sampleOrdinal(list, 2)).toBe(2);
  });
});

describe('разбор preview', () => {
  it('хороший ввод разбирается, null-площадь остаётся null', () => {
    const parsed = parseStylePreview(goodPreview);
    expect(parsed?.classes?.monolith.area_m2).toBeNull();
    expect(parsed?.classes?.shaft.area_m2).toBe(1.5);
    expect(parsed?.rejected_samples[0]?.reason).toBe('no_arc_at_point');
  });

  it('без признаков: classes и field_sources - null', () => {
    const parsed = parseStylePreview({ ...goodPreview, classes: null, field_sources: null });
    expect(parsed?.classes).toBeNull();
  });

  it('плохой ввод - null', () => {
    expect(parseStylePreview(null)).toBeNull();
    expect(parseStylePreview({})).toBeNull();
    expect(parseStylePreview({ ...goodPreview, unclassified_fill_share: 2 })).toBeNull();
    expect(
      parseStylePreview({
        ...goodPreview,
        classes: { ...goodPreview.classes, door: { pen_max_width: 'x' } },
      }),
    ).toBeNull();
  });
});

describe('тексты', () => {
  it('нет площади - не ноль', () => {
    expect(areaText(null)).toBe('площадь не определена: нет масштаба листа');
    expect(areaText(undefined)).toContain('не определена');
    expect(areaText(0)).toContain('м²');
  });

  it('доля в процентах или «—»', () => {
    expect(shareText(null)).toBe('—');
    expect(shareText(0.125)).toContain('12,5');
  });

  it('источник профиля', () => {
    expect(profileSourceText({ kind: 'samples', page_index: 2 })).toBe('по образцам, лист 3');
    expect(profileSourceText({ kind: 'manual' })).toBe('вручную');
  });
});
