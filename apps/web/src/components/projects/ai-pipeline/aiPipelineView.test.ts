import type { ProjectAiSheetRow } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import { rowView, styleDetail } from './aiPipelineView';

const row = (overrides: Partial<ProjectAiSheetRow> = {}): ProjectAiSheetRow => ({
  document_name: 'АР.pdf',
  revision_id: 'rev-1',
  page_index: 0,
  sheet_position: 1,
  sheet_title: 'План',
  convert_job_id: 'conv-1',
  view: 1,
  walls_job_id: null,
  review_available: false,
  stage1: { state: 'ok' },
  ...overrides,
});

describe('styleDetail', () => {
  it('нет оформления - нет строки', () => {
    expect(styleDetail(null)).toBeNull();
    expect(styleDetail(undefined)).toBeNull();
  });

  it('показывает найденные классы и применённые регионы', () => {
    expect(
      styleDetail({ state: 'ok', classes_found: 2, regions_applied: 8, error_message: null }),
    ).toBe('Оформление: классов 2, применено регионов 8');
    expect(styleDetail({ state: 'ok', classes_found: 0, regions_applied: null })).toBe(
      'Оформление: классов 0',
    );
  });

  it('идёт, ждёт и ошибка', () => {
    expect(styleDetail({ state: 'running' })).toBe('Оформление: идёт');
    expect(styleDetail({ state: 'not_started' })).toBe('Оформление: ждёт запуска');
    expect(styleDetail({ state: 'failed', error_message: 'Claude не ответил' })).toBe(
      'Оформление: ошибка · Claude не ответил',
    );
  });
});

describe('rowView этап 1', () => {
  it('ошибка этапа важнее оформления, иначе пояснение - оформление', () => {
    const style = { state: 'ok', classes_found: 1, regions_applied: 3 } as const;
    expect(rowView(row({ style }), 1)?.detail).toBe('Оформление: классов 1, применено регионов 3');
    expect(
      rowView(row({ style, stage1: { state: 'failed', error_message: 'движок упал' } }), 1)?.detail,
    ).toBe('движок упал');
    expect(rowView(row(), 1)?.detail).toBeNull();
  });
});
