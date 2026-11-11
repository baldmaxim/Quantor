import * as client from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { extractSummary } from './__fixtures__';
import { SheetPassportExtractPanel } from './SheetPassportExtractPanel';

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof client>()),
  getSheetPassportExtractSummary: vi.fn(),
  startSheetPassportExtract: vi.fn(),
}));

const ok = (data: unknown) => Promise.resolve({ data }) as never;

const mount = () => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={queryClient}>
      <SheetPassportExtractPanel projectId="p-1" />
    </QueryClientProvider>,
  );
};

describe('Панель разбора листов', () => {
  beforeEach(() => {
    vi.mocked(client.getSheetPassportExtractSummary).mockReset();
    vi.mocked(client.startSheetPassportExtract).mockReset();
  });

  it('заданий не было — ни статуса, ни итога', async () => {
    vi.mocked(client.getSheetPassportExtractSummary).mockImplementation(() => ok(null));
    mount();
    await waitFor(() => expect(client.getSheetPassportExtractSummary).toHaveBeenCalled());
    expect(screen.queryByTestId('extract-result')).toBeNull();
    expect(screen.getByRole('button', { name: 'Разобрать листы' })).toBeEnabled();
  });

  it('показывает счётчики итога и не раскрывает список ошибок, когда их нет', async () => {
    vi.mocked(client.getSheetPassportExtractSummary).mockImplementation(() => ok(extractSummary()));
    mount();
    const result = await screen.findByTestId('extract-result');
    expect(result).toHaveTextContent(
      'Разобрано файлов 2 из 3, страниц 7; новых 5, обновлено 2, не тронуто проверенных 1',
    );
    expect(within(result).queryByText(/Файлов с ошибкой/)).toBeNull();
  });

  it('число, которого нет в итоге, — прочерк, а не 0', async () => {
    vi.mocked(client.getSheetPassportExtractSummary).mockImplementation(() =>
      ok(extractSummary({ pages: null, skipped_reviewed: null, files_total: null })),
    );
    mount();
    expect(await screen.findByTestId('extract-result')).toHaveTextContent(
      'Разобрано файлов 2 из —, страниц —; новых 5, обновлено 2, не тронуто проверенных —',
    );
  });

  it('при ошибках раскрывает имена файлов', async () => {
    vi.mocked(client.getSheetPassportExtractSummary).mockImplementation(() =>
      ok(
        extractSummary({
          error_count: 1,
          errors: [{ file_name: 'Битый.pdf', error: 'PdfReadError' }],
        }),
      ),
    );
    mount();
    const toggle = await screen.findByText('Файлов с ошибкой: 1');
    await userEvent.click(toggle);
    expect(screen.getByText(/Битый\.pdf/)).toBeVisible();
  });

  it('пока задание идёт — прогресс и кнопка заблокирована, итог не показан', async () => {
    vi.mocked(client.getSheetPassportExtractSummary).mockImplementation(() =>
      ok(
        extractSummary({
          status: 'running',
          progress: 0.4,
          finished_at: null,
          files_total: null,
          files_parsed: null,
        }),
      ),
    );
    mount();
    expect(await screen.findByText('идёт разбор')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Разобрать листы' })).toBeDisabled();
    expect(screen.queryByTestId('extract-result')).toBeNull();
  });
});
