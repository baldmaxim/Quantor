import type * as ApiClient from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  docs: vi.fn(),
  links: vi.fn(),
  coverage: vi.fn(),
  upload: vi.fn(),
  remove: vi.fn(),
  put: vi.fn(),
}));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  listCadVorDocuments: mocks.docs,
  listCadVorLinks: mocks.links,
  readCadVorCoverage: mocks.coverage,
  uploadCadVor: mocks.upload,
  deleteCadVorDocument: mocks.remove,
  putCadVorLinks: mocks.put,
}));

import { MAX_VOR_BYTES } from './vor';
import { coverage, vorDocument } from './vor-fixtures';
import {
  useCadVorCoverage,
  useCadVorDocuments,
  useCadVorLinks,
  useDeleteCadVor,
  usePutCadVorLinks,
  useUploadCadVor,
  vorErrorText,
} from './vor-queries';

const PARAMS = { projectId: 'p1', revisionId: 'r1', jobId: 'j1', attempt: 1, pageIndex: 0, view: 1 };

const mount = () => {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false }, mutations: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  return renderHook(
    () => ({
      docs: useCadVorDocuments('p1', true),
      links: useCadVorLinks('p1', true),
      coverage: useCadVorCoverage(PARAMS, true, 1),
      upload: useUploadCadVor('p1'),
      remove: useDeleteCadVor('p1'),
      put: usePutCadVorLinks('p1'),
    }),
    { wrapper },
  );
};

const file = (name: string, size: number): File => {
  const made = new File(['x'], name);
  Object.defineProperty(made, 'size', { value: size });
  return made;
};

describe('запросы ВОР', () => {
  beforeEach(() => {
    for (const mock of Object.values(mocks)) mock.mockReset();
    mocks.docs.mockResolvedValue({ data: [vorDocument()] });
    mocks.links.mockResolvedValue({ data: [] });
    mocks.coverage.mockResolvedValue({ data: coverage() });
    mocks.upload.mockResolvedValue({ data: vorDocument({ id: 'd2' }) });
    mocks.remove.mockResolvedValue({ data: undefined });
    mocks.put.mockResolvedValue({ data: [] });
  });

  const loaded = async () => {
    const hook = mount();
    await waitFor(() => {
      expect(hook.result.current.docs.isSuccess).toBe(true);
      expect(hook.result.current.links.isSuccess).toBe(true);
      expect(hook.result.current.coverage.isSuccess).toBe(true);
    });
    return hook;
  };

  const calls = () => [mocks.docs, mocks.links, mocks.coverage].map((mock) => mock.mock.calls.length);

  it('загрузка ВОР: multipart-файл через клиент, список, связи и сверка перечитываются', async () => {
    const { result } = await loaded();
    const xlsx = file('ВОР.xlsx', 1000);
    await act(async () => {
      await result.current.upload.mutateAsync({ file: xlsx });
    });
    expect(mocks.upload).toHaveBeenCalledWith({
      throwOnError: true,
      path: { project_id: 'p1' },
      body: { file: xlsx },
    });
    await waitFor(() => expect(calls()).toEqual([2, 2, 2]));
  });

  it('замена: прежние документы удаляются после загрузки нового', async () => {
    const { result } = await loaded();
    await act(async () => {
      await result.current.upload.mutateAsync({ file: file('ВОР.xlsx', 10), replaceIds: ['d1'] });
    });
    expect(mocks.remove).toHaveBeenCalledWith({
      throwOnError: true,
      path: { project_id: 'p1', document_id: 'd1' },
    });
    expect(mocks.upload.mock.invocationCallOrder[0]).toBeLessThan(mocks.remove.mock.invocationCallOrder[0] ?? 0);
  });

  it('удаление ВОР перечитывает список, связи и сверку', async () => {
    const { result } = await loaded();
    await act(async () => {
      await result.current.remove.mutateAsync('d1');
    });
    await waitFor(() => expect(calls()).toEqual([2, 2, 2]));
  });

  it('PUT связей: тело с полным набором строк, список, связи и сверка перечитываются', async () => {
    const { result } = await loaded();
    await act(async () => {
      await result.current.put.mutateAsync({ groupKey: 'masonry|100|', itemIds: ['i1', 'i2'] });
    });
    expect(mocks.put).toHaveBeenCalledWith({
      throwOnError: true,
      path: { project_id: 'p1', group_key: 'masonry|100|' },
      body: { vor_item_ids: ['i1', 'i2'] },
    });
    await waitFor(() => expect(calls()).toEqual([2, 2, 2]));
  });

  it('файл больше 20 МБ и не .xlsx: отказ до отправки, сервер не вызывается', async () => {
    const { result } = await loaded();
    let error: unknown = null;
    await act(async () => {
      await result.current.upload
        .mutateAsync({ file: file('ВОР.xlsx', MAX_VOR_BYTES + 1) })
        .catch((reason: unknown) => {
          error = reason;
        });
    });
    expect(vorErrorText(error)).toBe('Файл больше 20 МБ: ВОР не загружен.');
    await act(async () => {
      await result.current.upload.mutateAsync({ file: file('ВОР.xls', 5) }).catch(() => undefined);
    });
    expect(mocks.upload).not.toHaveBeenCalled();
  });
});
