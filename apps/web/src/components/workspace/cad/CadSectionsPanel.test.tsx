import type { SectionLevelRead, SectionsRead } from '@quantor/api-client';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CadSectionsPanel } from './CadSectionsPanel';
import type { IWorkspaceCadSections } from './types';

const box = [0.1, 0.1, 0.2, 0.2] as [number, number, number, number];

const level = (over: Partial<SectionLevelRead> & { id: string }): SectionLevelRead => ({
  job_id: 'job',
  seq: 0,
  page_index: 3,
  cut: '1-1',
  corps: null,
  section: null,
  floor: 5,
  elevation_mm: 47600,
  upper_elevation_mm: 50900,
  clear_height_mm: 3000,
  structure_mm: 300,
  evidence: '',
  markup: { upper_mark: box, lower_mark: box, band: box, dims: [] },
  status: 'candidate',
  decided_by: null,
  decided_at: null,
  ...over,
});

const read = (over: Partial<SectionsRead> = {}): SectionsRead => ({
  revision_id: 'rev',
  job: {
    job_id: 'j',
    revision_id: 'rev',
    status: 'succeeded',
    attempt: 1,
    error_code: null,
    error_message: null,
    page_indexes: null,
    created_at: '2026-11-12T10:00:00Z',
    finished_at: '2026-11-12T10:01:00Z',
  },
  result_job_id: 'j',
  levels: [level({ id: 'a' }), level({ id: 'b', clear_height_mm: null, elevation_mm: 0 })],
  issues: [{ code: 'x', message: 'Размер не найден', page_index: 3, bbox: null }],
  pages: [
    { page_index: 3, title: 'Разрез 1-1', corps: '9', section: '3', cuts: ['1-1'], page_size_pt: [10, 10], rotation: 0 },
  ],
  ...over,
});

const props = (over: Partial<IWorkspaceCadSections> = {}): IWorkspaceCadSections => ({
  status: 'ready',
  data: read(),
  loadError: null,
  onReload: vi.fn(),
  pageIndex: 3,
  isSectionPage: true,
  starting: false,
  onStart: vi.fn(),
  deciding: false,
  onDecide: vi.fn(),
  actionError: null,
  activeLevelId: null,
  onSelectLevel: vi.fn(),
  markupVisible: true,
  onMarkupVisibleChange: vi.fn(),
  onOpenPage: vi.fn(),
  ...over,
});

describe('CadSectionsPanel', () => {
  it('лист-разрез: уровни с отметкой и высотами, замечания страницы', () => {
    render(<CadSectionsPanel {...props()} />);
    expect(screen.getByText('+47,600')).toBeTruthy();
    expect(screen.getByText(/в свету 3000 \/ пол\+плита 300/)).toBeTruthy();
    expect(screen.getByText('Размер не найден')).toBeTruthy();
  });

  it('«Принять» без высоты недоступна; «Принять все» берёт только допустимых', () => {
    const onDecide = vi.fn();
    render(<CadSectionsPanel {...props({ onDecide })} />);
    const accept = screen.getAllByRole('button', { name: 'Принять' });
    expect((accept[1] as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: /Принять все на листе/ }));
    expect(onDecide).toHaveBeenCalledWith(['a'], 'accept');
  });

  it('задание идёт: кнопка запуска заблокирована, виден статус', () => {
    const data = read({ job: { ...read().job!, status: 'running' } });
    render(<CadSectionsPanel {...props({ data })} />);
    expect((screen.getByRole('button', { name: /Распознать разрезы/ }) as HTMLButtonElement).disabled).toBe(true);
    expect(screen.getByText('Выполняется')).toBeTruthy();
  });

  it('на странице-разрезе повторный запуск называется «заново»', () => {
    render(<CadSectionsPanel {...props()} />);
    expect(screen.getByRole('button', { name: 'Распознать разрезы заново' })).toBeTruthy();
    expect(screen.queryByTestId('sections-summary')).toBeNull();
  });

  it('ошибка задания показывает причину', () => {
    const data = read({
      job: { ...read().job!, status: 'failed', error_code: 'CAD_ENGINE_FAILED', error_message: 'сбой' },
    });
    render(<CadSectionsPanel {...props({ data })} />);
    expect(screen.getByRole('alert').textContent).toContain('сбой');
  });

  it('ни одного запуска: подсказка и кнопка «Распознать разрезы»', () => {
    const data = read({ job: null, result_job_id: null, levels: [], pages: [], issues: [] });
    render(<CadSectionsPanel {...props({ data })} />);
    expect(screen.getByRole('button', { name: 'Распознать разрезы' })).toBeTruthy();
    expect(screen.getByText(/ещё не распознавались/)).toBeTruthy();
  });
});
