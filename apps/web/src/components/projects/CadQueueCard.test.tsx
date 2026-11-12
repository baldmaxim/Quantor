import type * as ApiClient from '@quantor/api-client';
import type { CadQueueItemRead, CadQueueRead } from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ queue: vi.fn() }));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  readCadQueue: mocks.queue,
}));

import { CadQueueCard } from './CadQueueCard';

const item = (overrides: Partial<CadQueueItemRead> = {}): CadQueueItemRead => ({
  job_id: 'j-1',
  job_type: 'cad_pdf_convert',
  status: 'queued',
  revision_id: 'rev-1',
  document_id: 'doc-1',
  document_name: 'АР План.pdf',
  pages: [81],
  created_at: '2026-11-12T10:00:00Z',
  started_at: null,
  finished_at: null,
  attempt: 0,
  max_attempts: 3,
  ahead: null,
  error_code: null,
  ...overrides,
});

const respond = (items: CadQueueItemRead[], totals = { running_total: 1, queued_total: 2 }) => {
  const data: CadQueueRead = { items, ...totals };
  mocks.queue.mockResolvedValue({ data });
};

const renderCard = () =>
  render(
    <QueryClientProvider client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}>
      <CadQueueCard projectId="p-1" />
    </QueryClientProvider>,
  );

describe('CadQueueCard', () => {
  beforeEach(() => {
    mocks.queue.mockReset();
  });

  it('сводка исполнителя по всем проектам', async () => {
    respond([item()], { running_total: 2, queued_total: 7 });
    renderCard();
    expect(await screen.findByTestId('cad-queue-summary')).toHaveTextContent(
      'Исполнитель: выполняется 2, в очереди 7 (все проекты)',
    );
    expect(mocks.queue).toHaveBeenCalledWith(
      expect.objectContaining({ path: { project_id: 'p-1' } }),
    );
  });

  it('пусто: «Заданий CAD нет»', async () => {
    respond([], { running_total: 0, queued_total: 0 });
    renderCard();
    expect(await screen.findByText('Заданий CAD нет')).toBeInTheDocument();
  });

  it('в очереди: место и ссылка на лист', async () => {
    respond([item({ ahead: 3 })]);
    renderCard();
    const row = (await screen.findAllByRole('listitem'))[0] as HTMLElement;
    expect(row).toHaveTextContent('CAD');
    expect(row).toHaveTextContent('В очереди · перед ним 3 задания');
    expect(row).toHaveTextContent('АР План.pdf · стр. 82');
    expect(within(row).getByRole('link')).toHaveAttribute(
      'href',
      '/projects/p-1/workspace?revision=rev-1&page=82&tab=cad',
    );
  });

  it('следующее на исполнение: ahead = 0', async () => {
    respond([item({ ahead: 0 })]);
    renderCard();
    expect(await screen.findByText('В очереди · следующее на исполнение')).toBeInTheDocument();
  });

  it('выполняется, попытка и тип задания', async () => {
    respond([
      item({
        job_type: 'cad_walls',
        status: 'running',
        started_at: '2026-11-12T10:05:00Z',
        attempt: 2,
      }),
    ]);
    renderCard();
    const row = (await screen.findAllByRole('listitem'))[0] as HTMLElement;
    expect(row).toHaveTextContent('Конструкции');
    expect(row).toHaveTextContent(/Выполняется с \d{2}:\d{2}/);
    expect(row).toHaveTextContent('попытка 2/3');
  });

  it('первая попытка не подписывается', async () => {
    respond([item({ status: 'running', attempt: 1 })]);
    renderCard();
    const row = (await screen.findAllByRole('listitem'))[0] as HTMLElement;
    expect(row).not.toHaveTextContent('попытка');
  });

  it('завершённые: готово, ошибка с текстом, отменено', async () => {
    respond([
      item({ job_id: 'a', status: 'succeeded', finished_at: '2026-11-12T10:10:00Z' }),
      item({ job_id: 'b', status: 'failed', error_code: 'CAD_AUTO_SCALE_UNCONFIRMED' }),
      item({ job_id: 'c', status: 'cancelled' }),
    ]);
    renderCard();
    const rows = await screen.findAllByRole('listitem');
    expect(rows[0]).toHaveTextContent(/Готово \d{2}:\d{2}/);
    expect(rows[1]).toHaveTextContent('Ошибка');
    expect(rows[1]?.querySelector('.text-danger')?.textContent ?? '').not.toBe('');
    expect(rows[2]).toHaveTextContent('Отменено');
  });

  it('без ревизии строка не ссылка', async () => {
    respond([item({ revision_id: null, document_name: null, document_id: null })]);
    renderCard();
    await screen.findAllByRole('listitem');
    expect(screen.queryByRole('link')).toBeNull();
  });

  it('отказ загрузки: ошибка и повтор', async () => {
    mocks.queue.mockRejectedValue(new Error('сеть'));
    renderCard();
    expect(await screen.findByText('Не удалось получить очередь CAD')).toBeInTheDocument();
  });
});
