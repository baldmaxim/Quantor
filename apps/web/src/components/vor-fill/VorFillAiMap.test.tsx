import * as client from '@quantor/api-client';
import type { AiVorMapRead } from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { render, screen, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { vorItem } from '@/lib/cad/vor-fixtures';

import { VorFillAiMap } from './VorFillAiMap';

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof client>()),
  readVorAiMap: vi.fn(),
  startVorAiMap: vi.fn(),
  listCadVorLinks: vi.fn(),
  putCadVorLinks: vi.fn(),
}));

const ok = (data: unknown) => Promise.resolve({ data }) as never;

const state = (patch: Partial<AiVorMapRead> = {}): AiVorMapRead => ({
  available: true,
  job_id: 'j1',
  status: 'succeeded',
  error_message: null,
  stale: false,
  model: 'claude-opus-5-5',
  prompt_version: 1,
  suggestions: [
    {
      item: vorItem({ id: 'i1', name: 'Кладка 190 мм', unit: 'м3' }),
      objects: [
        { group_key: 'masonry|190|', kind: 'construction', title: 'Кладка, 190 мм', linked: false },
      ],
      confidence: 'high',
      rationale: 'толщина и материал совпали',
    },
    {
      item: vorItem({ id: 'i2', name: 'Дверь', unit: 'шт' }),
      objects: [{ group_key: 'door|x|900x2100', kind: 'door', title: 'Дверь 900', linked: false }],
      confidence: 'low',
      rationale: 'размер неясен',
    },
  ],
  unmatched: [],
  limitations: [],
  ...patch,
});

const mount = () => {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <VorFillAiMap projectId="p1" />
    </QueryClientProvider>,
  );
};

beforeEach(() => {
  vi.resetAllMocks();
  vi.mocked(client.listCadVorLinks).mockReturnValue(ok([]));
  vi.mocked(client.putCadVorLinks).mockReturnValue(ok([]));
});

describe('ИИ-сопоставление ВОР', () => {
  it('вне пилота блока нет', async () => {
    vi.mocked(client.readVorAiMap).mockReturnValue(ok(state({ available: false })));
    mount();
    await vi.waitFor(() => expect(client.readVorAiMap).toHaveBeenCalled());
    expect(screen.queryByRole('region', { name: 'ИИ-сопоставление' })).not.toBeInTheDocument();
  });

  it('показывает предложения с уверенностью и обоснованием', async () => {
    vi.mocked(client.readVorAiMap).mockReturnValue(ok(state()));
    mount();
    const list = await screen.findByRole('region', { name: 'ИИ-сопоставление' });
    expect(within(list).getByText('Кладка 190 мм')).toBeInTheDocument();
    expect(within(list).getByText(/Кладка, 190 мм/)).toBeInTheDocument();
    expect(within(list).getByText(/толщина и материал совпали/)).toBeInTheDocument();
    expect(within(list).getByText('Уверенность: Высокая')).toHaveClass('text-success');
    expect(within(list).getByText('Готово: claude-opus-5-5, промт v1')).toBeInTheDocument();
  });

  it('«Принять» добавляет строку к прежним связям группы', async () => {
    vi.mocked(client.readVorAiMap).mockReturnValue(ok(state()));
    vi.mocked(client.listCadVorLinks).mockReturnValue(
      ok([
        {
          id: 'l1',
          group_key: 'masonry|190|',
          item: vorItem({ id: 'old' }),
          created_at: '2026-11-25T10:00:00Z',
        },
      ]),
    );
    mount();
    const user = userEvent.setup();
    const row = (await screen.findByText('Кладка 190 мм')).closest('li') as HTMLElement;
    await user.click(within(row).getByRole('button', { name: 'Принять' }));
    await vi.waitFor(() => expect(client.putCadVorLinks).toHaveBeenCalledTimes(1));
    const call = vi.mocked(client.putCadVorLinks).mock.calls[0]?.[0];
    expect(call?.path).toEqual({ project_id: 'p1', group_key: 'masonry|190|' });
    expect(call?.body).toEqual({ vor_item_ids: ['old', 'i1'] });
  });

  it('«Принять все» берёт только высокую уверенность', async () => {
    vi.mocked(client.readVorAiMap).mockReturnValue(ok(state()));
    mount();
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole('button', { name: /Принять все с высокой уверенностью \(1\)/ }),
    );
    await vi.waitFor(() => expect(client.putCadVorLinks).toHaveBeenCalledTimes(1));
    expect(vi.mocked(client.putCadVorLinks).mock.calls[0]?.[0]?.path).toEqual({
      project_id: 'p1',
      group_key: 'masonry|190|',
    });
  });

  it('«Отклонить» скрывает предложение без запросов связи', async () => {
    vi.mocked(client.readVorAiMap).mockReturnValue(ok(state()));
    mount();
    const user = userEvent.setup();
    const row = (await screen.findByText('Дверь')).closest('li') as HTMLElement;
    await user.click(within(row).getByRole('button', { name: 'Отклонить' }));
    expect(screen.queryByText('Дверь')).not.toBeInTheDocument();
    expect(client.putCadVorLinks).not.toHaveBeenCalled();
  });

  it('запуск зовёт сервер; во время задания кнопка закрыта', async () => {
    vi.mocked(client.readVorAiMap).mockReturnValue(
      ok(state({ status: 'running', suggestions: [] })),
    );
    mount();
    expect(await screen.findByText('Claude сопоставляет позиции…')).toBeInTheDocument();
    expect(
      screen.getByRole('button', { name: 'Предложить сопоставление (Claude)' }),
    ).toBeDisabled();
  });

  it('кнопка запуска вызывает запуск', async () => {
    vi.mocked(client.readVorAiMap).mockReturnValue(ok(state({ status: null, suggestions: [] })));
    vi.mocked(client.startVorAiMap).mockReturnValue(ok(state({ status: 'queued' })));
    mount();
    const user = userEvent.setup();
    await user.click(
      await screen.findByRole('button', { name: 'Предложить сопоставление (Claude)' }),
    );
    expect(client.startVorAiMap).toHaveBeenCalledTimes(1);
  });

  it('устаревший результат предложений не показывает', async () => {
    vi.mocked(client.readVorAiMap).mockReturnValue(ok(state({ stale: true, suggestions: [] })));
    mount();
    expect(await screen.findByText(/предложения устарели/)).toBeInTheDocument();
  });
});
