import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const api = vi.hoisted(() => ({
  readCadSheetRisers: vi.fn(),
  putCadSheetRisers: vi.fn(),
}));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<object>()),
  ...api,
}));

import { risersKeys, sheetOf, useCadRisers, useSaveCadRisers } from './risers-queries';

const SHEET = { projectId: 'p1', revisionId: 'r1', pageIndex: 81, view: 1 };
const ENTRY = {
  system: 'V1' as const,
  mark: 'В1.1.1',
  dn_mm: 50,
  role: 'own' as const,
  count: 1,
  shaft_id: null,
  source: null,
  note: null,
};

const setup = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return { client, wrapper };
};

describe('запросы реестра стояков', () => {
  beforeEach(() => vi.clearAllMocks());

  it('лист из параметров вида', () => {
    expect(
      sheetOf({
        projectId: 'p1',
        revisionId: 'r1',
        jobId: 'j',
        attempt: 2,
        pageIndex: 81,
        view: 1,
      }),
    ).toEqual(SHEET);
  });

  it('чтение: проект в пути, ревизия, страница и вид в запросе', async () => {
    const out = { revision_id: 'r1', page_index: 81, view: 1, risers: [ENTRY], updated_at: null };
    api.readCadSheetRisers.mockResolvedValue({ data: out });
    const { wrapper } = setup();
    const { result } = renderHook(() => useCadRisers(SHEET), { wrapper });
    await waitFor(() => expect(result.current.data).toEqual(out));
    expect(api.readCadSheetRisers).toHaveBeenCalledWith({
      throwOnError: true,
      path: { project_id: 'p1' },
      query: { revision_id: 'r1', page_index: 81, view: 1 },
    });
  });

  it('запись: PUT списком, ответ кладётся в кеш листа', async () => {
    const out = {
      revision_id: 'r1',
      page_index: 81,
      view: 1,
      risers: [ENTRY],
      updated_at: '2026-11-11T10:00:00Z',
    };
    api.putCadSheetRisers.mockResolvedValue({ data: out });
    const { client, wrapper } = setup();
    const { result } = renderHook(() => useSaveCadRisers(SHEET), { wrapper });
    await act(async () => {
      await result.current.mutateAsync([ENTRY]);
    });
    expect(api.putCadSheetRisers).toHaveBeenCalledWith({
      throwOnError: true,
      path: { project_id: 'p1' },
      query: { revision_id: 'r1', page_index: 81, view: 1 },
      body: { risers: [ENTRY] },
    });
    expect(client.getQueryData(risersKeys.sheet(SHEET))).toEqual(out);
  });
});
