import * as client from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { renderHook, waitFor } from '@testing-library/react';
import type { FC, ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import * as queries from '@/lib/queries';

import { candidate, question, questionsOut } from './fixtures';
import { useAttentionQueue } from './useAttentionQueue';

vi.mock('@/lib/queries', async (importOriginal) => ({
  ...(await importOriginal<typeof queries>()),
  useFeatures: vi.fn(),
  useProjectDocuments: vi.fn(),
  useProjectRevisions: vi.fn(),
}));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof client>()),
  readPipelineAuto: vi.fn(),
  getDocQuestions: vi.fn(),
  readCadPipeline: vi.fn(),
}));

const ok = (data: unknown) => Promise.resolve({ data }) as never;

const wrapper = (): FC<{ children: ReactNode }> => {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const Wrapper: FC<{ children: ReactNode }> = ({ children }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
  return Wrapper;
};

const setup = (enabled: boolean) => {
  window.localStorage.clear();
  vi.mocked(queries.useFeatures).mockReturnValue({ 'project.consistency': true });
  vi.mocked(queries.useProjectDocuments).mockReturnValue({ data: { items: [] } } as never);
  vi.mocked(queries.useProjectRevisions).mockReturnValue({ byDocument: new Map() } as never);
  vi.mocked(client.readPipelineAuto)
    .mockReset()
    .mockImplementation(() => ok({ enabled }));
  vi.mocked(client.getDocQuestions)
    .mockReset()
    .mockImplementation(() => ok(questionsOut([question({ candidates: [candidate()] })])));
};

describe('useAttentionQueue', () => {
  beforeEach(() => vi.clearAllMocks());

  it('при выключенном автопайплайне вопросов нет и запросов за ними нет', async () => {
    setup(false);
    const { result } = renderHook(() => useAttentionQueue('p-1'), { wrapper: wrapper() });

    await waitFor(() => expect(client.readPipelineAuto).toHaveBeenCalled());

    expect(result.current.enabled).toBe(false);
    expect(result.current.items).toEqual([]);
    expect(result.current.open).toBe(false);
    expect(client.getDocQuestions).not.toHaveBeenCalled();
  });

  it('при включённом автопайплайне собирает вопросы и сам открывает окно', async () => {
    setup(true);
    const { result } = renderHook(() => useAttentionQueue('p-1'), { wrapper: wrapper() });

    await waitFor(() => expect(result.current.items).toHaveLength(1));
    await waitFor(() => expect(result.current.open).toBe(true));
  });

  it('после «Позже» вопрос пропадает и записан в localStorage на сутки', async () => {
    setup(true);
    const { result } = renderHook(() => useAttentionQueue('p-1'), { wrapper: wrapper() });
    await waitFor(() => expect(result.current.items).toHaveLength(1));

    result.current.snooze('doc:clear_height');

    await waitFor(() => expect(result.current.items).toHaveLength(0));
    const stored = JSON.parse(
      window.localStorage.getItem('quantor:attention:snooze:p-1') ?? '{}',
    ) as Record<string, number>;
    expect(stored['doc:clear_height']).toBeGreaterThan(Date.now() + 23 * 60 * 60 * 1000);
  });
});
