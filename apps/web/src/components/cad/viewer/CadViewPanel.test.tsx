import { render, screen, within } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type * as Queries from '@/lib/cad/view-queries';

import { diagnostics, FRAME_NO, job, JOB_ID, scale, SHA } from './fixtures';

const view = vi.hoisted(() => ({ current: {} as Record<string, unknown> }));

vi.mock('@/lib/cad/view-queries', async (importOriginal) => ({
  ...(await importOriginal<typeof Queries>()),
  useCadView: () => view.current,
}));
// Холст проверяется отдельно (CadViewerPane.test.tsx): здесь панель отдаёт ему заголовок и
// разделы боковой панели, а заглушка выводит их все, чтобы проверить их содержимое.
vi.mock('./CadViewerPane', () => ({
  CadViewerPane: ({
    heading,
    extraTabs,
  }: {
    heading: ReactNode;
    extraTabs: readonly { id: string; label: string; content: ReactNode }[];
  }) => (
    <div data-testid="pane">
      {heading}
      {extraTabs.map((tab) => (
        <section key={tab.id} aria-label={tab.label}>
          {tab.content}
        </section>
      ))}
    </div>
  ),
}));

import { CadViewPanel } from './CadViewPanel';

const mount = (patch: Parameters<typeof job>[0] = {}) =>
  render(
    <CadViewPanel
      projectId="p1"
      revisionId="r1"
      job={job(patch)}
      pageIndex={0}
      view={1}
      jobContent={<p>содержимое задания</p>}
    />,
  );

const ready = (data: ReturnType<typeof diagnostics>) => {
  view.current = { isPending: false, isError: false, data, refetch: vi.fn() };
};

beforeEach(() => {
  view.current = { isPending: true, isError: false, data: undefined, refetch: vi.fn() };
});

describe('CadViewPanel', () => {
  it('без результата попытки ничего не запрашивает и говорит об этом', () => {
    mount({ result_attempt: null });
    expect(screen.getByText('Результат попытки ещё не готов')).toBeInTheDocument();
    expect(screen.queryByTestId('pane')).toBeNull();
  });

  it('пока вид грузится - скелетон', () => {
    mount();
    expect(screen.getByRole('status', { name: 'Загрузка вида' })).toBeInTheDocument();
  });

  it('409 CAD_RESULT_NOT_READY - понятный текст', () => {
    view.current = {
      isPending: false,
      isError: true,
      error: { detail: { code: 'CAD_RESULT_NOT_READY' } },
      refetch: vi.fn(),
    };
    mount();
    expect(screen.getByText('Результат попытки ещё не готов')).toBeInTheDocument();
  });

  it('заголовок: страница PDF и вид; приёмка всегда не выполнена', () => {
    ready(diagnostics());
    mount();
    expect(screen.getByRole('heading', { name: 'Стр. 1 · вид 1' })).toBeInTheDocument();
    expect(screen.getByTestId('cad-acceptance')).toHaveTextContent(
      'Инженерная приёмка: не выполнена',
    );
  });

  it('индекс страницы показывается, только если он отличается от номера PDF', () => {
    ready(diagnostics({ legacy_pdf_page: 5, page_index: 0 }));
    mount();
    expect(screen.getByText('индекс страницы: 1')).toBeInTheDocument();
  });

  it('DXF выпущен: нужна проверка, DXF скачивается, SHA-256 виден', () => {
    ready(diagnostics());
    mount();
    expect(screen.getByText(/DXF выпущен · нужна проверка/)).toBeInTheDocument();
    const link = screen.getByRole('link', { name: 'Скачать DXF' });
    expect(link).toHaveAttribute('download');
    expect(link.getAttribute('href')).toContain(
      `/cad/${JOB_ID}/artifacts/views/p001_v01/plan_candidates.dxf`,
    );
    expect(screen.getByTestId('cad-dxf-sha')).toHaveTextContent(SHA);
  });

  it('диагностика без DXF: DXF не создан, кнопки скачивания DXF нет', () => {
    ready(
      diagnostics({
        status: 'done',
        result_status: 'no_cad_review_required',
        dxf: null,
        preview_available: false,
        frame: FRAME_NO,
        scale: scale({
          status: 'no_controls',
          passed: false,
          mm_per_pdf_point: null,
          scale_denominator: null,
          hold_reasons: ['Не найдено размерных цепочек.'],
        }),
        files: [{ name: 'views/p001_v01/scale.json', sha256: 'b'.repeat(64), size: 512 }],
      }),
    );
    mount();
    expect(screen.getByText(/Только диагностика · DXF не создан/)).toBeInTheDocument();
    expect(screen.queryByRole('link', { name: 'Скачать DXF' })).toBeNull();
    expect(screen.getByText('DXF в этой попытке не создан.')).toBeInTheDocument();
    expect(screen.getByText('Не найдено размерных цепочек.')).toBeInTheDocument();
  });

  it('ошибка вида отличается от остальных исходов', () => {
    ready(
      diagnostics({
        status: 'error',
        result_status: 'failed',
        dxf: null,
        preview_available: false,
      }),
    );
    mount();
    expect(screen.getByText(/Вид завершился ошибкой/)).toBeInTheDocument();
  });

  it('HOLD: причины списком; без причин - подтверждён размерной проверкой', () => {
    ready(
      diagnostics({
        scale: scale({ passed: false, hold_reasons: ['Нет независимой проверки (holdout).'] }),
      }),
    );
    const first = mount();
    expect(screen.getByText(/HOLD/)).toBeInTheDocument();
    expect(screen.getByText('Нет независимой проверки (holdout).')).toBeInTheDocument();
    first.unmount();

    ready(diagnostics());
    mount();
    expect(screen.queryByText(/HOLD/)).toBeNull();
    expect(screen.getByText('Подтверждён размерной проверкой')).toBeInTheDocument();
  });

  it('таблица контролей: пустые значения - прочерк, а не 0; вне допуска - ✗', () => {
    ready(diagnostics());
    mount();
    const table = screen.getByRole('region', { name: 'Контроли масштаба' });
    const rows = within(table).getAllByRole('row');
    const holdout = rows[2];
    expect(holdout).toBeDefined();
    const cells = within(holdout as HTMLElement).getAllByRole('cell');
    // chain_id, роль, подпись, по масштабу, невязка, допуск, в допуске
    expect(cells[0]).toHaveTextContent('—');
    expect(cells[2]).toHaveTextContent('—');
    expect(cells[4]).toHaveTextContent('—');
    expect(cells[6]).toHaveTextContent('✗');
    expect(within(rows[1] as HTMLElement).getByText('✓ да')).toBeInTheDocument();
  });

  it('кадр не подтверждён - показана причина', () => {
    ready(diagnostics({ frame: FRAME_NO }));
    mount();
    expect(screen.getAllByText(FRAME_NO.reason ?? '').length).toBeGreaterThan(0);
  });

  it('напечатанный масштаб - отдельная строка, а не подтверждение', () => {
    ready(diagnostics());
    mount();
    expect(screen.getByText('Напечатанный масштаб')).toBeInTheDocument();
    // «1:100» дважды: подобранный масштаб и напечатанный - разные строки.
    expect(screen.getAllByText('1:100', { selector: 'dd' })).toHaveLength(2);
  });
});
