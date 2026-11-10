import { describe, expect, it } from 'vitest';

import { EMPTY_SELECTION } from './selection';
import {
  cadRedirectHref,
  jobCoversPage,
  pageForJob,
  parseWorkspaceJob,
  sheetPosition,
  workspaceCadHref,
} from './workspace-url';

const REVISION = '11111111-1111-4111-8111-111111111111';
const JOB = '22222222-2222-4222-8222-222222222222';
const SHEETS = [{ page_index: 0 }, { page_index: 1 }, { page_index: 4 }];

describe('позиция листа', () => {
  it('позиция с 1 по индексу страницы PDF', () => {
    expect(sheetPosition(SHEETS, 0)).toBe(1);
    expect(sheetPosition(SHEETS, 4)).toBe(3);
  });

  it('листа нет - null', () => {
    expect(sheetPosition(SHEETS, 2)).toBeNull();
  });
});

describe('workspaceCadHref', () => {
  it('ревизия, лист, вкладка, задание и вид', () => {
    expect(
      workspaceCadHref('p1', { revision: REVISION, position: 3, job: JOB, view: 2 }),
    ).toBe(`/projects/p1/workspace?revision=${REVISION}&page=3&tab=cad&job=${JOB}&view=2`);
  });

  it('только ревизия - вкладка CAD без листа', () => {
    expect(
      workspaceCadHref('p1', { revision: REVISION, position: null, job: null, view: null }),
    ).toBe(`/projects/p1/workspace?revision=${REVISION}&tab=cad`);
  });

  it('ревизии нет - только вкладка', () => {
    expect(workspaceCadHref('p1', { revision: null, position: 2, job: JOB, view: 1 })).toBe(
      '/projects/p1/workspace?tab=cad',
    );
  });

  it('вид без задания не пишется', () => {
    expect(
      workspaceCadHref('p1', { revision: REVISION, position: 1, job: null, view: 3 }),
    ).toBe(`/projects/p1/workspace?revision=${REVISION}&page=1&tab=cad`);
  });
});

describe('перевод адреса страницы CAD', () => {
  it('индекс страницы переводится в позицию листа рабочей области', () => {
    const selection = { revision: REVISION, job: JOB, page: 4, view: 2 };
    expect(cadRedirectHref('p1', selection, SHEETS)).toBe(
      `/projects/p1/workspace?revision=${REVISION}&page=3&tab=cad&job=${JOB}&view=2`,
    );
  });

  it('задание без листа: лист в адрес не попадает', () => {
    const selection = { revision: REVISION, job: JOB, page: null, view: null };
    expect(cadRedirectHref('p1', selection, SHEETS)).toBe(
      `/projects/p1/workspace?revision=${REVISION}&tab=cad&job=${JOB}`,
    );
  });

  it('только ревизия', () => {
    expect(cadRedirectHref('p1', { ...EMPTY_SELECTION, revision: REVISION }, null)).toBe(
      `/projects/p1/workspace?revision=${REVISION}&tab=cad`,
    );
  });

  it('ревизии нет - просто вкладка CAD', () => {
    expect(cadRedirectHref('p1', EMPTY_SELECTION, null)).toBe('/projects/p1/workspace?tab=cad');
  });

  it('список листов не получен - позиция по индексу', () => {
    const selection = { revision: REVISION, job: JOB, page: 2, view: 1 };
    expect(cadRedirectHref('p1', selection, null)).toContain('&page=3&');
    // листа нет в списке - тоже по индексу
    expect(cadRedirectHref('p1', { ...selection, page: 7 }, SHEETS)).toContain('&page=8&');
  });
});

describe('задание и вид из адреса рабочей области', () => {
  const params = (query: string) => new URLSearchParams(query);

  it('читает валидные значения', () => {
    expect(parseWorkspaceJob(params(`job=${JOB}&view=2`))).toEqual({ job: JOB, view: 2 });
  });

  it('невалидное задание отбрасывается вместе с видом', () => {
    expect(parseWorkspaceJob(params('job=abc&view=2'))).toEqual({ job: null, view: null });
    expect(parseWorkspaceJob(params('view=2'))).toEqual({ job: null, view: null });
  });

  it('невалидный вид отбрасывается', () => {
    expect(parseWorkspaceJob(params(`job=${JOB}&view=x`))).toEqual({ job: JOB, view: null });
  });
});

describe('задание и лист', () => {
  it('закрывает лист, если страницы не названы или лист среди них', () => {
    expect(jobCoversPage({ requested_pages: null }, 3)).toBe(true);
    expect(jobCoversPage({ requested_pages: [] }, 3)).toBe(true);
    expect(jobCoversPage({ requested_pages: [1, 3] }, 3)).toBe(true);
    expect(jobCoversPage({ requested_pages: [1, 2] }, 3)).toBe(false);
  });

  it('выбор задания: текущий лист, если он закрыт, иначе первая страница задания', () => {
    expect(pageForJob({ requested_pages: [1, 3] }, 3)).toBe(3);
    expect(pageForJob({ requested_pages: [5, 2] }, 3)).toBe(2);
    expect(pageForJob({ requested_pages: null }, 3)).toBe(3);
    expect(pageForJob({ requested_pages: [5, 2] }, null)).toBe(2);
  });
});
