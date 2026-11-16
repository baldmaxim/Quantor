import type { FacadeViewRead, FacadesRead } from '@quantor/api-client';
import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

import { CadFacadesPanel } from './CadFacadesPanel';
import type { IWorkspaceCadFacades } from './types';

const box = [0.1, 0.1, 0.2, 0.2] as [number, number, number, number];

const view = (over: Partial<FacadeViewRead> & { id: string }): FacadeViewRead => ({
  axes: [{ label: '1', x: 0.1, y: 0.9, u_mm: 0 }],
  axis_from: '1',
  axis_to: '8',
  bbox: box,
  body: 'vector',
  corps: '9',
  section: null,
  decided_at: null,
  decided_by: null,
  floors: [{ bbox: box, floor: 2, label: '2 этаж', mark_mm: 3000 }],
  job_id: 'j',
  marks: [
    { bbox: box, text: '+3,000', value_mm: 3000, used: true },
    { bbox: box, text: '+6,000', value_mm: 6000, used: true },
    { bbox: box, text: '+9,000', value_mm: 9000, used: true },
  ],
  mm_per_pt: 10,
  page_index: 4,
  residual_mm: 1,
  scale_status: 'fitted',
  seq: 0,
  status: 'candidate',
  title: 'Фасад 1-8',
  view_key: 'k',
  window_count: 2,
  windows: [
    {
      bbox: box,
      height_mm: 1500,
      source: 'observed',
      u0_mm: 1000,
      u1_mm: 2800,
      width_mm: 1800,
      z_bottom_mm: 900,
      z_top_mm: 2400,
    },
    {
      bbox: box,
      height_mm: 1500,
      source: 'observed',
      u0_mm: null,
      u1_mm: null,
      width_mm: 1200,
      z_bottom_mm: 3900,
      z_top_mm: 5400,
    },
  ],
  ...over,
});

const read = (over: Partial<FacadesRead> = {}): FacadesRead => ({
  revision_id: 'rev',
  job: {
    job_id: 'j',
    revision_id: 'rev',
    status: 'succeeded',
    attempt: 1,
    error_code: null,
    error_message: null,
    page_indexes: null,
    created_at: '2026-11-16T10:00:00Z',
    finished_at: '2026-11-16T10:01:00Z',
  },
  result_job_id: 'j',
  views: [view({ id: 'a' }), view({ id: 'b', scale_status: 'none', title: 'Фасад Г-А', seq: 1 })],
  issues: [{ code: 'x', message: 'Окно без отметки', page_index: 4, bbox: null }],
  ...over,
});

const props = (over: Partial<IWorkspaceCadFacades> = {}): IWorkspaceCadFacades => ({
  status: 'ready',
  data: read(),
  loadError: null,
  onReload: vi.fn(),
  starting: false,
  onStart: vi.fn(),
  deciding: false,
  onDecide: vi.fn(),
  actionError: null,
  activeViewId: null,
  onSelectView: vi.fn(),
  onPanelShown: vi.fn(),
  onOpenPage: vi.fn(),
  ...over,
});

describe('CadFacadesPanel', () => {
  it('показывает виды по странице: оси, тип, привязку, число окон и замечания', () => {
    render(<CadFacadesPanel {...props()} />);
    expect(screen.getByText('Стр. 5')).toBeTruthy();
    expect(screen.getByText('Фасад 1-8')).toBeTruthy();
    expect(screen.getAllByText(/оси 1–8/).length).toBe(2);
    expect(screen.getByText(/привязан по 3 отметкам/)).toBeTruthy();
    expect(screen.getByText(/не привязан/)).toBeTruthy();
    expect(screen.getAllByText(/окон: 2/).length).toBe(2);
    expect(screen.getByText('Окно без отметки')).toBeTruthy();
  });

  it('таблица окон: размеры в мм, не определено - «—», не 0', () => {
    render(<CadFacadesPanel {...props()} />);
    const rows = screen.getAllByTestId('facade-window');
    expect(rows.length).toBe(4);
    expect(rows[0]?.textContent).toContain('900');
    expect(rows[0]?.textContent).toContain('1000–2800');
    expect(rows[1]?.textContent).toContain('—–—');
  });

  it('«Принять» недоступна без привязки по отметкам', () => {
    render(<CadFacadesPanel {...props()} />);
    const accept = screen.getAllByRole('button', { name: /^Принять: / });
    expect((accept[0] as HTMLButtonElement).disabled).toBe(false);
    expect((accept[1] as HTMLButtonElement).disabled).toBe(true);
    expect(accept[1]?.getAttribute('title')).toMatch(/не привязан/);
  });

  it('решения вызывают onDecide', () => {
    const onDecide = vi.fn();
    render(
      <CadFacadesPanel
        {...props({
          onDecide,
          data: read({ views: [view({ id: 'a' }), view({ id: 'r', status: 'rejected', seq: 1, title: 'Фасад Р' })] }),
        })}
      />,
    );
    fireEvent.click(screen.getByRole('button', { name: 'Принять: Фасад 1-8' }));
    expect(onDecide).toHaveBeenLastCalledWith(['a'], 'accept');
    fireEvent.click(screen.getByRole('button', { name: 'Отклонить: Фасад 1-8' }));
    expect(onDecide).toHaveBeenLastCalledWith(['a'], 'reject');
    fireEvent.click(screen.getByRole('button', { name: 'Сбросить: Фасад Р' }));
    expect(onDecide).toHaveBeenLastCalledWith(['r'], 'reset');
  });

  it('запуск и переход на страницу вида', () => {
    const onStart = vi.fn();
    const onOpenPage = vi.fn();
    const onSelectView = vi.fn();
    render(<CadFacadesPanel {...props({ onStart, onOpenPage, onSelectView })} />);
    fireEvent.click(screen.getByRole('button', { name: 'Разобрать фасады заново' }));
    expect(onStart).toHaveBeenCalled();
    fireEvent.click(screen.getAllByTitle('Открыть страницу вида')[0]!);
    expect(onOpenPage).toHaveBeenCalledWith(4);
    expect(onSelectView).toHaveBeenCalledWith('a');
  });

  it('упавшее задание показывает ошибку, без заданий - предложение запуска', () => {
    const failed = read({
      job: { ...read().job!, status: 'failed', error_code: null, error_message: 'сбой' },
      result_job_id: null,
      views: [],
    });
    const { unmount } = render(<CadFacadesPanel {...props({ data: failed })} />);
    expect(screen.getByRole('alert').textContent).toContain('сбой');
    unmount();
    render(<CadFacadesPanel {...props({ data: read({ job: null, result_job_id: null, views: [] }) })} />);
    expect(screen.getByRole('button', { name: 'Разобрать фасады' })).toBeTruthy();
  });
});
