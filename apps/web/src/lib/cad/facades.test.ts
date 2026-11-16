import type { FacadeViewRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import {
  acceptableFacadeCandidateIds,
  canAcceptFacade,
  countFacades,
  facadeAxesText,
  facadeBodyText,
  facadeReviewGroups,
  facadeScaleText,
  groupFacadesByPage,
  isFacadesJobActive,
  markOrEmpty,
  mmOrEmpty,
} from './facades';

const mark = (used: boolean) => ({ bbox: [0, 0, 1, 1] as [number, number, number, number], text: 't', value_mm: 0, used });

describe('facades', () => {
  it('привязка по отметкам: текст по статусу', () => {
    expect(facadeScaleText({ scale_status: 'fitted', marks: [mark(true), mark(true), mark(false)] })).toBe(
      'привязан по 2 отметкам',
    );
    expect(facadeScaleText({ scale_status: 'weak', marks: [] })).toBe('привязан по двум отметкам');
    expect(facadeScaleText({ scale_status: 'text_only', marks: [] })).toBe(
      'отметки без знаков: уровни только числами',
    );
    expect(facadeScaleText({ scale_status: 'none', marks: [] })).toBe('не привязан');
  });

  it('принять можно только привязанный и непринятый вид', () => {
    expect(canAcceptFacade({ scale_status: 'fitted', status: 'candidate' })).toBe(true);
    expect(canAcceptFacade({ scale_status: 'weak', status: 'rejected' })).toBe(true);
    expect(canAcceptFacade({ scale_status: 'fitted', status: 'accepted' })).toBe(false);
    expect(canAcceptFacade({ scale_status: 'text_only', status: 'candidate' })).toBe(false);
    expect(canAcceptFacade({ scale_status: 'none', status: 'candidate' })).toBe(false);
  });

  it('пустое значение - «—», не 0', () => {
    expect(mmOrEmpty(null)).toBe('—');
    expect(mmOrEmpty(undefined)).toBe('—');
    expect(mmOrEmpty(0)).toBe('0');
    expect(markOrEmpty(null)).toBe('—');
    expect(markOrEmpty(3000)).toBe('+3,000');
    expect(facadeAxesText({ axis_from: null, axis_to: null })).toBe('—');
    expect(facadeAxesText({ axis_from: '1', axis_to: '8' })).toBe('оси 1–8');
    expect(facadeBodyText('raster')).toBe('растровый (только отметки)');
    expect(facadeBodyText('vector')).toBe('векторный');
  });

  it('виды группируются по странице', () => {
    const views = [
      { id: 'a', page_index: 5, seq: 1 },
      { id: 'b', page_index: 2, seq: 0 },
      { id: 'c', page_index: 5, seq: 0 },
    ] as FacadeViewRead[];
    const groups = groupFacadesByPage(views);
    expect(groups.map((g) => g.pageIndex)).toEqual([2, 5]);
    expect(groups[1]?.views.map((v) => v.id)).toEqual(['c', 'a']);
  });

  it('список приёмки: первой группа открытого листа, остальные по номеру; фильтр скрывает строки', () => {
    const views = [
      { id: 'a', page_index: 5, seq: 1, status: 'accepted', scale_status: 'fitted' },
      { id: 'b', page_index: 2, seq: 0, status: 'candidate', scale_status: 'none' },
      { id: 'c', page_index: 5, seq: 0, status: 'candidate', scale_status: 'weak' },
      { id: 'd', page_index: 7, seq: 0, status: 'rejected', scale_status: 'fitted' },
    ] as FacadeViewRead[];
    const shape = (groups: ReturnType<typeof facadeReviewGroups>) =>
      groups.map((g) => [g.pageIndex, g.current, g.views.map((v) => v.id)]);
    expect(shape(facadeReviewGroups(views, 5))).toEqual([
      [5, true, ['c', 'a']],
      [2, false, ['b']],
      [7, false, ['d']],
    ]);
    expect(shape(facadeReviewGroups(views, null))).toEqual([
      [2, false, ['b']],
      [5, false, ['c', 'a']],
      [7, false, ['d']],
    ]);
    expect(shape(facadeReviewGroups(views, 5, 'candidate'))).toEqual([
      [5, true, ['c']],
      [2, false, ['b']],
    ]);
    expect(countFacades(views)).toEqual({ total: 4, accepted: 1, candidate: 2, rejected: 1 });
    expect(acceptableFacadeCandidateIds(views)).toEqual(['c']);
  });

  it('задание идёт: queued и running', () => {
    expect(isFacadesJobActive('queued')).toBe(true);
    expect(isFacadesJobActive('running')).toBe(true);
    expect(isFacadesJobActive('succeeded')).toBe(false);
    expect(isFacadesJobActive(undefined)).toBe(false);
  });
});
