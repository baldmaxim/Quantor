import { describe, expect, it } from 'vitest';

import {
  EMPTY_SELECTION,
  parseSelection,
  selectionQuery,
  viewSelectionKind,
  withJob,
  withRevision,
  withView,
} from './selection';

const REV = '11111111-1111-4111-8111-111111111111';
const JOB = '22222222-2222-4222-8222-222222222222';

describe('выбор в адресе', () => {
  it('разбирает и собирает адрес без потерь', () => {
    const selection = { revision: REV, job: JOB, page: 2, view: 1 };
    const params = new URLSearchParams(selectionQuery(selection));
    expect(parseSelection(params)).toEqual(selection);
  });

  it('отбрасывает невалидные значения', () => {
    expect(parseSelection(new URLSearchParams('revision=abc&job=' + JOB))).toEqual(EMPTY_SELECTION);
    expect(parseSelection(new URLSearchParams(`revision=${REV}&job=x&page=1&view=1`))).toEqual({
      revision: REV,
      job: null,
      page: null,
      view: null,
    });
    expect(
      parseSelection(new URLSearchParams(`revision=${REV}&job=${JOB}&page=-1&view=1`)).page,
    ).toBeNull();
  });

  it('смена ревизии сбрасывает задание и вид, смена задания — вид', () => {
    const full = { revision: REV, job: JOB, page: 0, view: 1 };
    expect(withRevision('другая')).toEqual({ ...EMPTY_SELECTION, revision: 'другая' });
    expect(withJob(full, null)).toEqual({ revision: REV, job: null, page: null, view: null });
    expect(withView(withJob(full, JOB), 3, 2)).toEqual({
      revision: REV,
      job: JOB,
      page: 3,
      view: 2,
    });
  });
});

describe('что показать для выбранного вида', () => {
  const job = (patch: Record<string, unknown> = {}) =>
    ({
      result_attempt: 2,
      result_status: 'completed_requires_review',
      pages: [{ index: 0, views: [{ view: 1 }] }],
      ...patch,
    }) as unknown as Parameters<typeof viewSelectionKind>[0];
  const attempt = (number: number, outcome = 'succeeded') =>
    ({ attempt: number, outcome }) as unknown as Parameters<typeof viewSelectionKind>[1];

  it('не выбран - ничего', () => {
    expect(viewSelectionKind(job(), attempt(2), null, null)).toBe('none');
  });

  it('результат выпущен и это та же попытка - панель просмотра', () => {
    expect(viewSelectionKind(job(), attempt(2), 0, 1)).toBe('panel');
    expect(
      viewSelectionKind(job({ result_status: 'no_cad_review_required' }), attempt(2), 0, 1),
    ).toBe('panel');
  });

  it('попытка с отказом - без панели и без запроса', () => {
    expect(viewSelectionKind(job({ result_status: 'failed' }), attempt(2, 'failed'), 0, 1)).toBe(
      'failed',
    );
    // Отказ и у более новой попытки, чем результат.
    expect(viewSelectionKind(job(), attempt(3, 'failed'), 0, 1)).toBe('failed');
    expect(viewSelectionKind(job({ result_status: 'failed' }), attempt(2), 0, 1)).toBe('failed');
  });

  it('другая попытка, нет вида или нет итога - недоступно', () => {
    expect(viewSelectionKind(job(), attempt(1), 0, 1)).toBe('unavailable');
    expect(viewSelectionKind(job(), attempt(2), 0, 9)).toBe('unavailable');
    expect(viewSelectionKind(job({ result_status: null }), attempt(2), 0, 1)).toBe('unavailable');
    expect(viewSelectionKind(job({ result_attempt: null }), attempt(2), 0, 1)).toBe('unavailable');
    expect(viewSelectionKind(job(), null, 0, 1)).toBe('unavailable');
  });
});
