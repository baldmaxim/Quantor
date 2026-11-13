import type * as ApiClient from '@quantor/api-client';
import type { AdminJobRead } from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({ list: vi.fn(), cancel: vi.fn(), session: vi.fn() }));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  listAdminJobs: mocks.list,
  cancelAdminJobs: mocks.cancel,
  readSession: mocks.session,
}));

import { QueueBoard } from './QueueBoard';

const job = (overrides: Partial<AdminJobRead> = {}): AdminJobRead => ({
  id: 'j-1',
  project_id: 'p-1',
  project_name: 'Башня А',
  workspace_id: 'w-1',
  scope: 'project',
  job_type: 'cad_pdf_convert',
  status: 'queued',
  progress: null,
  stage: null,
  error_code: null,
  error_message: null,
  attempt: 0,
  max_attempts: 3,
  worker_id: null,
  lease_expires_at: null,
  heartbeat_at: null,
  available_at: '2026-11-13T10:00:00Z',
  started_at: null,
  finished_at: null,
  created_at: '2026-11-13T10:00:00Z',
  updated_at: '2026-11-13T10:00:00Z',
  is_retryable: false,
  ...overrides,
});

const JOBS = [
  job({ id: 'j-1', status: 'running', progress: 0.4, stage: 'рендер' }),
  job({ id: 'j-2' }),
  job({ id: 'j-3', project_id: 'p-2', project_name: 'Башня Б', job_type: 'cad_walls' }),
];

const setup = (
  permissions: string[],
  projectId: string | null = null,
  jobs: AdminJobRead[] = JOBS,
) => {
  mocks.session.mockResolvedValue({ data: { authenticated: true, permissions } });
  mocks.list.mockResolvedValue({
    data: { items: jobs, total: jobs.length, limit: 500, offset: 0 },
  });
  mocks.cancel.mockResolvedValue({
    data: { cancelled: 2, skipped: 1, cancelled_ids: ['j-1', 'j-2'] },
  });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const onProjectChange = vi.fn();
  render(
    <QueryClientProvider client={client}>
      <QueueBoard projectId={projectId} onProjectChange={onProjectChange} />
    </QueryClientProvider>,
  );
  return { onProjectChange };
};

describe('очередь заданий', () => {
  beforeEach(() => {
    mocks.list.mockReset();
    mocks.cancel.mockReset();
    mocks.session.mockReset();
  });

  it('показывает счётчики и строки с проектом-ссылкой', async () => {
    setup(['system.admin', 'jobs.manage']);
    expect(await screen.findByTestId('queue-counts')).toHaveTextContent(
      'выполняется 1 · в очереди 2',
    );
    expect(screen.getAllByRole('link', { name: 'Башня А' })[0]).toHaveAttribute(
      'href',
      '/projects/p-1',
    );
    expect(mocks.list).toHaveBeenCalledWith(
      expect.objectContaining({ query: expect.objectContaining({ active: true }) }),
    );
  });

  it('«Отменить выбранные» отправляет job_ids выбранных после подтверждения', async () => {
    const user = userEvent.setup();
    setup(['system.admin', 'jobs.manage']);
    const selectedButton = await screen.findByRole('button', { name: /Отменить выбранные \(0\)/ });
    expect(selectedButton).toBeDisabled();

    const boxes = screen.getAllByRole('checkbox');
    await user.click(boxes[0]!);
    await user.click(boxes[1]!);
    await user.click(screen.getByRole('button', { name: /Отменить выбранные \(2\)/ }));

    const dialog = await screen.findByRole('dialog');
    expect(dialog).toHaveTextContent('Выполняющиеся задания будут прерваны');
    await user.click(screen.getByRole('button', { name: 'Отменить задания' }));

    await waitFor(() =>
      expect(mocks.cancel).toHaveBeenCalledWith(
        expect.objectContaining({ body: { job_ids: ['j-1', 'j-2'], project_id: null } }),
      ),
    );
    expect(await screen.findByRole('status')).toHaveTextContent('Отменено 2, пропущено 1');
  });

  it('«Завершить всю очередь» отправляет all_active', async () => {
    const user = userEvent.setup();
    setup(['system.admin', 'jobs.manage']);
    await user.click(await screen.findByRole('button', { name: 'Завершить всю очередь' }));
    await user.click(await screen.findByRole('button', { name: 'Отменить задания' }));

    await waitFor(() =>
      expect(mocks.cancel).toHaveBeenCalledWith(
        expect.objectContaining({ body: { all_active: true, project_id: null } }),
      ),
    );
  });

  it('при фильтре по проекту отправляет all_active с project_id', async () => {
    const user = userEvent.setup();
    setup(['system.admin', 'jobs.manage'], 'p-1');
    await user.click(await screen.findByRole('button', { name: 'Завершить очередь проекта' }));
    await user.click(await screen.findByRole('button', { name: 'Отменить задания' }));

    await waitFor(() =>
      expect(mocks.cancel).toHaveBeenCalledWith(
        expect.objectContaining({ body: { all_active: true, project_id: 'p-1' } }),
      ),
    );
    expect(mocks.list).toHaveBeenCalledWith(
      expect.objectContaining({ query: expect.objectContaining({ project_id: 'p-1' }) }),
    );
  });

  it('кнопка в строке отменяет одно задание без подтверждения', async () => {
    const user = userEvent.setup();
    setup(['system.admin', 'jobs.manage']);
    const buttons = await screen.findAllByRole('button', { name: /^Отменить задание:/ });
    await user.click(buttons[1]!);

    await waitFor(() =>
      expect(mocks.cancel).toHaveBeenCalledWith(
        expect.objectContaining({ body: { job_ids: ['j-2'] } }),
      ),
    );
  });

  it('без права jobs.manage кнопок отмены и чекбоксов нет', async () => {
    setup(['system.admin']);
    await screen.findByTestId('queue-counts');
    expect(screen.queryByRole('button', { name: /Отменить/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('button', { name: /Завершить/ })).not.toBeInTheDocument();
    expect(screen.queryByRole('checkbox')).not.toBeInTheDocument();
  });

  it('без права jobs.read — «Нет доступа» и без запроса очереди', async () => {
    setup([]);
    expect(await screen.findByText('Нет доступа')).toBeInTheDocument();
  });

  it('пустая очередь', async () => {
    setup(['system.admin', 'jobs.manage'], null, []);
    expect(await screen.findByText('Очередь пуста')).toBeInTheDocument();
  });
});
