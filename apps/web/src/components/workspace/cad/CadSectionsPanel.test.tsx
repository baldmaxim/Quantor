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
  auto_accepted: false,
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
    {
      page_index: 3,
      title: 'Разрез 1-1',
      corps: '9',
      section: '3',
      cuts: ['1-1'],
      page_size_pt: [10, 10],
      rotation: 0,
    },
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
    const accept = screen.getAllByRole('button', { name: /^Принять: / });
    expect((accept[1] as HTMLButtonElement).disabled).toBe(true);
    fireEvent.click(screen.getByRole('button', { name: /Принять все/ }));
    expect(onDecide).toHaveBeenCalledWith(['a'], 'accept');
  });

  it('один список сверху вниз: автопринятый остаётся в нём с бейджем «Авто», сводка считает остаток', () => {
    const data = read({
      levels: [
        level({
          id: 'auto',
          status: 'accepted',
          auto_accepted: true,
          decided_at: '2026-11-16T00:00:00Z',
        }),
        level({ id: 'c', elevation_mm: 44300, upper_elevation_mm: 47600 }),
        level({ id: 'r', elevation_mm: 41000, upper_elevation_mm: 44300, status: 'rejected' }),
      ],
    });
    render(<CadSectionsPanel {...props({ data })} />);
    expect(screen.getByTestId('review-summary').textContent).toBe(
      'Осталось проверить: 1 из 3 · принято автоматически: 1',
    );
    expect(screen.getByText('Сверху вниз, как на листе')).toBeTruthy();
    const rows = screen.getAllByTestId('section-level');
    expect(rows.map((row) => row.getAttribute('data-status'))).toEqual([
      'accepted',
      'candidate',
      'rejected',
    ]);
    expect(rows[0]?.textContent).toContain('Авто');
    // Свёрнутых корзин нет: все строки в одном списке.
    expect(screen.queryByText(/^Принято \(/)).toBeNull();
  });

  it('строка после решения остаётся на месте: меняются бейдж и кнопки', () => {
    const levels = [
      level({ id: 'top', elevation_mm: 50900 }),
      level({ id: 'mid' }),
      level({ id: 'low', elevation_mm: 44300 }),
    ];
    const { rerender } = render(<CadSectionsPanel {...props({ data: read({ levels }) })} />);
    const marks = () => screen.getAllByTestId('section-level').map((row) => row.textContent);
    expect(marks()[1]).toContain('+47,600');
    expect(marks()[1]).toContain('Кандидат');
    const decided = levels.map((item) =>
      item.id === 'mid' ? { ...item, status: 'accepted' as const } : item,
    );
    rerender(<CadSectionsPanel {...props({ data: read({ levels: decided }) })} />);
    expect(marks()[1]).toContain('+47,600');
    expect(marks()[1]).toContain('Принят');
    expect(screen.getByTestId('review-summary').textContent).toContain(
      'Осталось проверить: 2 из 3',
    );
  });

  it('кнопки строки: у кандидата «Принять» и «Отклонить», у решённого - только «Вернуть»', () => {
    const onDecide = vi.fn();
    const data = read({
      levels: [level({ id: 'a' }), level({ id: 'd', elevation_mm: 44300, status: 'accepted' })],
    });
    render(<CadSectionsPanel {...props({ data, onDecide })} />);
    expect(screen.getAllByRole('button', { name: /^Принять: / }).length).toBe(1);
    expect(screen.getAllByRole('button', { name: /^Отклонить: / }).length).toBe(1);
    fireEvent.click(screen.getByRole('button', { name: /^Вернуть в кандидаты: / }));
    expect(onDecide).toHaveBeenLastCalledWith(['d'], 'reset');
    fireEvent.click(screen.getByRole('button', { name: /^Отклонить: / }));
    expect(onDecide).toHaveBeenLastCalledWith(['a'], 'reject');
  });

  it('фильтр по статусу скрывает строки; пункт с нулём недоступен', () => {
    const data = read({
      levels: [level({ id: 'a' }), level({ id: 'd', elevation_mm: 44300, status: 'accepted' })],
    });
    render(<CadSectionsPanel {...props({ data })} />);
    expect(screen.getByRole('button', { name: 'Все 2' }).getAttribute('aria-pressed')).toBe('true');
    expect((screen.getByRole('button', { name: 'Отклонено 0' }) as HTMLButtonElement).disabled).toBe(
      true,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Принято 1' }));
    const rows = screen.getAllByTestId('section-level');
    expect(rows.length).toBe(1);
    expect(rows[0]?.getAttribute('data-status')).toBe('accepted');
  });

  it('несколько разрезов на листе: группы с заголовком, один разрез - без заголовка', () => {
    const one = render(<CadSectionsPanel {...props()} />);
    expect(screen.queryByRole('heading', { name: 'Разрез 1-1', level: 5 })).toBeNull();
    one.unmount();
    const data = read({
      levels: [
        level({ id: 'a', seq: 0 }),
        level({ id: 'b', seq: 1, cut: '2-2', elevation_mm: 50900 }),
        level({ id: 'c', seq: 2, elevation_mm: 44300 }),
      ],
    });
    render(<CadSectionsPanel {...props({ data })} />);
    expect(screen.getByRole('heading', { name: 'Разрез 1-1', level: 5 })).toBeTruthy();
    expect(screen.getByRole('heading', { name: 'Разрез 2-2', level: 5 })).toBeTruthy();
    // Уровни разных разрезов не перемешаны по отметке: сначала весь 1-1, потом 2-2.
    expect(
      screen.getAllByTestId('section-level').map((row) => /[+±-]\d+,\d{3}/.exec(row.textContent ?? '')?.[0]),
    ).toEqual(['+47,600', '+44,300', '+50,900']);
  });

  it('все решения приняты: сводка говорит об этом, «Принять все» нет', () => {
    const data = read({ levels: [level({ id: 'a', status: 'accepted' })] });
    render(<CadSectionsPanel {...props({ data })} />);
    expect(screen.getByTestId('review-summary').textContent).toBe('Все решения приняты');
    expect(screen.queryByRole('button', { name: /Принять все/ })).toBeNull();
  });

  it('щелчок по уровню выделяет его (переход к участку листа), повторный - снимает', () => {
    const onSelectLevel = vi.fn();
    const { rerender } = render(<CadSectionsPanel {...props({ onSelectLevel })} />);
    const row = () => screen.getAllByTitle('Показать на листе')[0] as HTMLElement;
    fireEvent.click(row());
    expect(onSelectLevel).toHaveBeenLastCalledWith('a');
    rerender(<CadSectionsPanel {...props({ onSelectLevel, activeLevelId: 'a' })} />);
    fireEvent.click(row());
    expect(onSelectLevel).toHaveBeenLastCalledWith(null);
  });

  it('задание идёт: кнопка запуска заблокирована, виден статус', () => {
    const data = read({ job: { ...read().job!, status: 'running' } });
    render(<CadSectionsPanel {...props({ data })} />);
    expect(
      (screen.getByRole('button', { name: 'Распознать заново' }) as HTMLButtonElement).disabled,
    ).toBe(true);
    expect(screen.getByText('Выполняется')).toBeTruthy();
    expect(screen.getByText(/попытка 1/)).toBeTruthy();
  });

  it('результат есть: повторный запуск - вторичная кнопка внизу, статус завершённого задания скрыт', () => {
    const onStart = vi.fn();
    render(<CadSectionsPanel {...props({ onStart })} />);
    expect(screen.queryByRole('button', { name: 'Распознать разрезы' })).toBeNull();
    expect(screen.queryByText(/попытка/)).toBeNull();
    const again = screen.getByRole('button', { name: 'Распознать заново' });
    const rows = screen.getAllByTestId('section-level');
    // Кнопка стоит после списка уровней.
    expect(
      rows[rows.length - 1]!.compareDocumentPosition(again) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    fireEvent.click(again);
    expect(onStart).toHaveBeenCalled();
    expect(screen.queryByTestId('sections-summary')).toBeNull();
  });

  it('отказ действия виден наверху, рядом со сводкой', () => {
    render(<CadSectionsPanel {...props({ actionError: 'Принять нельзя' })} />);
    const alert = screen.getByRole('alert');
    expect(alert.textContent).toBe('Принять нельзя');
    expect(
      alert.compareDocumentPosition(screen.getAllByTestId('section-level')[0]!) &
        Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it('ошибка задания показывает причину', () => {
    const data = read({
      job: {
        ...read().job!,
        status: 'failed',
        error_code: 'CAD_ENGINE_FAILED',
        error_message: 'сбой',
      },
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
