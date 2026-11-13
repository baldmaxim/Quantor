import type * as ApiClient from '@quantor/api-client';
import type { CadProjectSummaryRead } from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ summary: vi.fn() }));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  readCadSummary: mocks.summary,
}));

import { CadRecognitionSummary } from './CadRecognitionSummary';

const summaryOf = (overrides: Partial<CadProjectSummaryRead>): CadProjectSummaryRead => ({
  sheets_total: 0,
  sheets_done: 0,
  sheets_running: 0,
  sheets_failed: 0,
  sheets_idle: 0,
  documents_total: 0,
  ...overrides,
});

const renderSummary = () =>
  render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <CadRecognitionSummary projectId="p-1" />
    </QueryClientProvider>,
  );

describe('CadRecognitionSummary', () => {
  beforeEach(() => {
    mocks.summary.mockReset();
  });

  it('заголовок, процент и подписи-счётчики без нулевых', async () => {
    mocks.summary.mockResolvedValue({
      data: summaryOf({
        sheets_total: 8,
        sheets_done: 4,
        sheets_running: 2,
        sheets_failed: 0,
        sheets_idle: 2,
        documents_total: 2,
      }),
    });
    renderSummary();
    expect(await screen.findByText('Распознавание: 4 из 8 листов · 50 %')).toBeInTheDocument();
    const labels = screen.getAllByRole('listitem').map((item) => item.textContent);
    expect(labels).toEqual(['Готово 4', 'Идёт 2', 'Не запускались 2']);
    expect(mocks.summary).toHaveBeenCalledWith(
      expect.objectContaining({ path: { project_id: 'p-1' } }),
    );
  });

  it('полоса: описание словами и ширина сегментов в процентах', async () => {
    mocks.summary.mockResolvedValue({
      data: summaryOf({ sheets_total: 4, sheets_done: 2, sheets_failed: 1, sheets_idle: 1 }),
    });
    renderSummary();
    const bar = await screen.findByRole('img');
    expect(bar).toHaveAttribute(
      'aria-label',
      'готово 2, идёт 0, ошибки 1, не запускались 1 из 4 листов',
    );
    const widths = Array.from(bar.children).map((segment) => (segment as HTMLElement).style.width);
    expect(widths).toEqual(['50%', '25%']);
  });

  it('нулевой проект: «Листов для CAD нет»', async () => {
    mocks.summary.mockResolvedValue({ data: summaryOf({}) });
    renderSummary();
    const block = await screen.findByTestId('cad-recognition-summary');
    expect(within(block).getByText('Листов для CAD нет')).toBeInTheDocument();
    expect(screen.queryByRole('img')).toBeNull();
  });

  it('ошибка: короткая строка и повтор запроса', async () => {
    mocks.summary.mockRejectedValueOnce(new Error('сеть'));
    mocks.summary.mockResolvedValue({ data: summaryOf({ sheets_total: 1, sheets_idle: 1 }) });
    renderSummary();
    expect(await screen.findByText('Не удалось получить сводку распознавания')).toBeInTheDocument();
    await userEvent.click(screen.getByRole('button', { name: 'Повторить' }));
    expect(await screen.findByText('Распознавание: 0 из 1 листов · 0 %')).toBeInTheDocument();
  });
});
