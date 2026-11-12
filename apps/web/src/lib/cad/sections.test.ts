import type { SectionLevelRead, SectionPageRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import {
  acceptableCandidateIds,
  canAcceptLevel,
  countLevels,
  formatLevelFloor,
  formatLevelHeights,
  formatMark,
  groupLevelsByCut,
  issuesOfPage,
  levelsOfPage,
  sectionPageLabel,
  sectionPageRows,
  routeLevelsText,
  sectionWarningText,
} from './sections';

const box = [0.1, 0.1, 0.2, 0.2] as [number, number, number, number];

const level = (over: Partial<SectionLevelRead> & { id: string }): SectionLevelRead => ({
  job_id: 'job',
  seq: 0,
  page_index: 3,
  cut: '1-1',
  corps: null,
  section: null,
  floor: null,
  elevation_mm: 0,
  upper_elevation_mm: 3300,
  clear_height_mm: 3000,
  structure_mm: 300,
  evidence: '',
  markup: { upper_mark: box, lower_mark: box, band: box, dims: [] },
  status: 'candidate',
  decided_by: null,
  decided_at: null,
  ...over,
});

describe('formatMark', () => {
  it('знак и запятая', () => {
    expect(formatMark(47600)).toBe('+47,600');
    expect(formatMark(-3200)).toBe('-3,200');
    expect(formatMark(0)).toBe('±0,000');
    expect(formatMark(3050)).toBe('+3,050');
    expect(formatMark(5)).toBe('+0,005');
  });
});

describe('formatLevelHeights / formatLevelFloor', () => {
  it('в свету и пол+плита', () => {
    expect(formatLevelHeights({ clear_height_mm: 3000, structure_mm: 300 })).toBe(
      'в свету 3000 / пол+плита 300',
    );
    expect(formatLevelHeights({ clear_height_mm: 3000, structure_mm: null })).toBe('в свету 3000');
    expect(formatLevelHeights({ clear_height_mm: null, structure_mm: null })).toBe(
      'высота не определена',
    );
  });
  it('этаж или прочерк', () => {
    expect(formatLevelFloor({ floor: 5 })).toBe('Этаж 5');
    expect(formatLevelFloor({ floor: null })).toBe('—');
  });
});

describe('принятие', () => {
  it('нельзя без высоты, вне пределов и уже принятое', () => {
    expect(canAcceptLevel({ status: 'candidate', clear_height_mm: 3000 })).toBe(true);
    expect(canAcceptLevel({ status: 'rejected', clear_height_mm: 1500 })).toBe(true);
    expect(canAcceptLevel({ status: 'candidate', clear_height_mm: null })).toBe(false);
    expect(canAcceptLevel({ status: 'candidate', clear_height_mm: 1499 })).toBe(false);
    expect(canAcceptLevel({ status: 'candidate', clear_height_mm: 6001 })).toBe(false);
    expect(canAcceptLevel({ status: 'accepted', clear_height_mm: 3000 })).toBe(false);
  });
  it('«принять все» берёт только кандидатов с допустимой высотой', () => {
    const levels = [
      level({ id: 'a' }),
      level({ id: 'b', clear_height_mm: null }),
      level({ id: 'c', status: 'accepted' }),
      level({ id: 'd', status: 'rejected' }),
      level({ id: 'e', clear_height_mm: 9000 }),
    ];
    expect(acceptableCandidateIds(levels)).toEqual(['a']);
  });
});

describe('группировка', () => {
  it('по линии разреза, внутри - сверху вниз; без обозначения - в конце', () => {
    const levels = [
      level({ id: 'n', seq: 0, cut: null, elevation_mm: 100 }),
      level({ id: 'a', seq: 1, cut: '2-2', elevation_mm: 0 }),
      level({ id: 'b', seq: 2, cut: '2-2', elevation_mm: 3300 }),
      level({ id: 'c', seq: 3, cut: '1-1', elevation_mm: 0 }),
    ];
    const groups = groupLevelsByCut(levels);
    expect(groups.map((group) => group.label)).toEqual([
      'Разрез 2-2',
      'Разрез 1-1',
      'Разрез без обозначения',
    ]);
    expect(groups[0]?.levels.map((item) => item.id)).toEqual(['b', 'a']);
  });
  it('пустое обозначение - как отсутствующее', () => {
    expect(groupLevelsByCut([level({ id: 'x', cut: '  ' })])[0]?.cut).toBeNull();
  });
});

describe('страницы и сводка', () => {
  const pages: SectionPageRead[] = [
    { page_index: 7, title: 'Разрез 2-2', corps: '9', section: '3', cuts: ['2-2'], page_size_pt: [1, 1], rotation: 0 },
    { page_index: 3, title: null, corps: null, section: null, cuts: [], page_size_pt: [1, 1], rotation: 0 },
  ];
  const levels = [
    level({ id: 'a', page_index: 3, status: 'accepted' }),
    level({ id: 'b', page_index: 3 }),
    level({ id: 'c', page_index: 7, status: 'rejected' }),
  ];
  it('счётчики по статусам', () => {
    expect(countLevels(levels)).toEqual({ total: 3, accepted: 1, candidate: 1, rejected: 1 });
  });
  it('страницы по номеру со сводкой', () => {
    const rows = sectionPageRows(pages, levels);
    expect(rows.map((row) => row.page.page_index)).toEqual([3, 7]);
    expect(rows[0]?.counts.accepted).toBe(1);
  });
  it('подпись страницы', () => {
    expect(sectionPageLabel(pages[0]!)).toBe('Стр. 8 · Разрез 2-2 · корп. 9, сек. 3');
    expect(sectionPageLabel(pages[1]!)).toBe('Стр. 4');
  });
  it('уровни и замечания страницы', () => {
    expect(levelsOfPage(levels, 3).map((item) => item.id)).toHaveLength(2);
    const issues = [
      { code: 'x', message: 'a', page_index: 3, bbox: null },
      { code: 'y', message: 'b', page_index: null, bbox: null },
    ];
    expect(issuesOfPage(issues, 3)).toHaveLength(1);
  });
});

describe('предупреждение трасс', () => {
  it('известный код - текст, неизвестный - как есть', () => {
    expect(sectionWarningText('section_level_ambiguous')).toContain('уточните уровни на листе разреза');
    expect(sectionWarningText('other')).toBe('other');
  });
});

describe('источник высоты у задания трасс', () => {
  it('разрезы, плита проекта и допущение движка', () => {
    expect(routeLevelsText({ levels_source: 'section', clear_height_mm: 3000 })).toBe(
      'Высота в свету: 3000 мм — по разрезам',
    );
    expect(routeLevelsText({ levels_source: 'project_slab', slab_thickness_mm: 250 })).toBe(
      'Плита 250 мм — из уровней проекта',
    );
    expect(routeLevelsText({ levels_source: 'none' })).toBe('Высота: допущение движка');
    expect(routeLevelsText({})).toBe('Высота: допущение движка');
  });
});
