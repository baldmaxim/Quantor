import type { SectionsRead } from '@quantor/api-client';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import type { IWorkspaceCadSectionsLink } from '@/components/workspace/cad/types';

import { CadMepSectionsLink } from './CadMepSectionsLink';

const box = [0.1, 0.1, 0.2, 0.2] as [number, number, number, number];
const level = (id: string, status: 'accepted' | 'candidate' | 'rejected', page = 3) => ({
  id,
  job_id: 'j',
  seq: 0,
  page_index: page,
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
  status,
  decided_by: null,
  decided_at: null,
});

const job = (status: string, extra: Record<string, unknown> = {}) =>
  ({
    job_id: 'j',
    revision_id: 'rev',
    status,
    attempt: 1,
    error_code: null,
    error_message: null,
    page_indexes: null,
    created_at: '2026-11-12T10:00:00Z',
    finished_at: null,
    ...extra,
  }) as unknown as SectionsRead['job'];

const read = (over: Partial<SectionsRead> = {}): SectionsRead => ({
  revision_id: 'rev',
  job: job('succeeded'),
  result_job_id: 'j',
  levels: [level('a', 'accepted'), level('b', 'candidate'), level('c', 'rejected')],
  issues: [],
  pages: [
    { page_index: 3, title: 'Разрез 1-1', corps: '9', section: '3', cuts: ['1-1'], page_size_pt: [10, 10], rotation: 0 },
  ],
  ...over,
});

const props = (over: Partial<IWorkspaceCadSectionsLink> = {}): IWorkspaceCadSectionsLink => ({
  status: 'ready',
  data: read(),
  starting: false,
  onStart: vi.fn(),
  onOpenPage: vi.fn(),
  actionError: null,
  ...over,
});

const empty = { job: null, result_job_id: null, levels: [], pages: [], issues: [] };

describe('CadMepSectionsLink', () => {
  it('разрезов нет: подсказка и кнопка запуска на документ', () => {
    const onStart = vi.fn();
    render(<CadMepSectionsLink {...props({ data: read(empty), onStart })} />);
    expect(screen.getByText('Разрезы ещё не распознавались')).toBeTruthy();
    fireEvent.click(screen.getByRole('button', { name: 'Распознать разрезы в документе' }));
    expect(onStart).toHaveBeenCalledTimes(1);
  });

  it('задание идёт: статус, кнопка заблокирована', () => {
    const data = read({ ...empty, job: job('running') });
    render(<CadMepSectionsLink {...props({ data })} />);
    expect(screen.getByText('Разрезы распознаются…')).toBeTruthy();
    expect(
      (screen.getByRole('button', { name: 'Распознать разрезы в документе' }) as HTMLButtonElement)
        .disabled,
    ).toBe(true);
  });

  it('ошибка задания показывает причину', () => {
    const data = read({
      ...empty,
      job: job('failed', { error_code: 'CAD_ENGINE_FAILED', error_message: 'сбой' }),
    });
    render(<CadMepSectionsLink {...props({ data })} />);
    expect(screen.getByRole('alert').textContent).toContain('сбой');
  });

  it('результат есть: счётчики и переход на страницу-разрез', () => {
    const onOpenPage = vi.fn();
    render(<CadMepSectionsLink {...props({ onOpenPage })} />);
    expect(screen.getByText('Высота из разрезов')).toBeTruthy();
    expect(screen.getByText(/Уровней: принято/).textContent).toBe(
      'Уровней: принято 1, кандидатов 1, отклонено 1',
    );
    fireEvent.click(screen.getByRole('button', { name: /Стр\. 4 · Разрез 1-1.* принято 1\/3/ }));
    expect(onOpenPage).toHaveBeenCalledWith(3);
  });

  it('результат без страниц-разрезов: «не найдены»', () => {
    const data = read({ pages: [], levels: [] });
    render(<CadMepSectionsLink {...props({ data })} />);
    expect(screen.getByText('Разрезы в документе не найдены.')).toBeTruthy();
  });
});
