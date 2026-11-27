import type * as ApiClient from '@quantor/api-client';
import type { AiPromptSummary } from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  list: vi.fn(),
  one: vi.fn(),
  create: vi.fn(),
  activate: vi.fn(),
  stats: vi.fn(),
  session: vi.fn(),
}));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  listAiPrompts: mocks.list,
  getAiPrompt: mocks.one,
  createAiPrompt: mocks.create,
  activateAiPrompt: mocks.activate,
  aiPromptStats: mocks.stats,
  readSession: mocks.session,
}));

import { AiPromptsBoard } from './AiPromptsBoard';

const row = (overrides: Partial<AiPromptSummary>): AiPromptSummary => ({
  id: 'p-1',
  role: 'corrector',
  version: 1,
  status: 'active',
  note: 'Исходный промт',
  created_by: null,
  created_at: '2026-11-25T10:00:00Z',
  activated_at: '2026-11-25T10:00:00Z',
  text_bytes: 12,
  ...overrides,
});

const VERSIONS = [row({ id: 'p-2', version: 2, status: 'draft', note: 'вторая' }), row({})];

const setup = (permissions: string[] = ['system.admin']) => {
  mocks.session.mockResolvedValue({ data: { authenticated: true, permissions } });
  mocks.list.mockResolvedValue({ data: VERSIONS });
  mocks.one.mockImplementation(({ path }: { path: { prompt_id: string } }) =>
    Promise.resolve({
      data: {
        ...(VERSIONS.find((v) => v.id === path.prompt_id) ?? VERSIONS[0]),
        text: `Текст ${path.prompt_id}`,
      },
    }),
  );
  mocks.stats.mockResolvedValue({
    data: {
      rows: [
        {
          prompt_id: 'p-1',
          role: 'corrector',
          version: 1,
          status: 'active',
          runs_total: 3,
          runs_succeeded: 2,
          runs_failed: 1,
          cost_avg_usd: 0.375,
          cost_sum_usd: 0.75,
          duration_avg_ms: 2000,
          verdicts: { needs_correction: 1 },
          findings_total: 3,
          findings_by_type: { monolith: 3 },
          remarks_open: 1,
          remarks_resolved: 1,
          remarks_deleted: 1,
        },
      ],
    },
  });
  mocks.create.mockResolvedValue({ data: { ...VERSIONS[0], id: 'p-3', version: 3, text: 'x' } });
  mocks.activate.mockResolvedValue({ data: { ...VERSIONS[0], status: 'active', text: 'x' } });
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={client}>
      <AiPromptsBoard />
    </QueryClientProvider>,
  );
};

describe('промты ИИ', () => {
  beforeEach(() => {
    Object.values(mocks).forEach((mock) => mock.mockReset());
  });

  it('показывает активную версию, список и статистику', async () => {
    setup();
    expect(await screen.findByText('Активная версия: v1')).toBeTruthy();
    expect(await screen.findByLabelText('Версии промта')).toBeTruthy();
    expect(await screen.findByText('Текст p-1')).toBeTruthy();
    expect(await screen.findByText('1 / 1 / 1')).toBeTruthy();
  });

  it('даёт вкладки всех ролей, включая оформление и координацию', async () => {
    setup();
    const user = userEvent.setup();
    await screen.findByText('Текст p-1');
    for (const [label, role] of [
      ['Сопоставление ВОР', 'vor_mapper'],
      ['Оформление', 'style'],
      ['Координация', 'coordination'],
    ] as const) {
      await user.click(screen.getByRole('button', { name: label }));
      await waitFor(() =>
        expect(mocks.list).toHaveBeenLastCalledWith(expect.objectContaining({ query: { role } })),
      );
    }
  });

  it('без права system.admin доступа нет', async () => {
    setup([]);
    expect(await screen.findByText('Нет доступа')).toBeTruthy();
    expect(mocks.list).not.toHaveBeenCalled();
  });

  it('создаёт версию с текстом активной в качестве основы', async () => {
    setup();
    const user = userEvent.setup();
    await screen.findByText('Текст p-1');
    await user.click(screen.getByRole('button', { name: 'Новая версия' }));
    const field = await screen.findByLabelText('Текст промта', { selector: 'textarea' });
    expect((field as HTMLTextAreaElement).value).toBe('Текст p-1');
    await user.type(screen.getByLabelText('Заметка'), 'правка');
    await user.click(screen.getByRole('button', { name: 'Создать черновик' }));
    await waitFor(() =>
      expect(mocks.create).toHaveBeenCalledWith(
        expect.objectContaining({
          body: { role: 'corrector', text: 'Текст p-1', note: 'правка' },
        }),
      ),
    );
  });

  it('активирует версию после подтверждения', async () => {
    setup();
    const user = userEvent.setup();
    await screen.findByText('Текст p-1');
    await user.click(screen.getByRole('button', { name: 'Сделать активной' }));
    expect(mocks.activate).not.toHaveBeenCalled();
    await user.click(await screen.findByRole('button', { name: 'Активировать' }));
    await waitFor(() =>
      expect(mocks.activate).toHaveBeenCalledWith(
        expect.objectContaining({ path: { prompt_id: 'p-2' } }),
      ),
    );
  });
});
