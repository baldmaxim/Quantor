import type * as ApiClient from '@quantor/api-client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { act, renderHook, waitFor } from '@testing-library/react';
import type { ReactNode } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const mocks = vi.hoisted(() => ({
  docs: vi.fn(),
  links: vi.fn(),
  coverage: vi.fn(),
  importRevision: vi.fn(),
  projectDocs: vi.fn(),
  projectRevisions: vi.fn(),
  remove: vi.fn(),
  put: vi.fn(),
}));

vi.mock('@quantor/api-client', async (importOriginal) => ({
  ...(await importOriginal<typeof ApiClient>()),
  listCadVorDocuments: mocks.docs,
  listCadVorLinks: mocks.links,
  readCadVorCoverage: mocks.coverage,
  importCadVorFromRevision: mocks.importRevision,
  listProjectDocuments: mocks.projectDocs,
  listProjectRevisions: mocks.projectRevisions,
  deleteCadVorDocument: mocks.remove,
  putCadVorLinks: mocks.put,
}));

import { coverage, vorDocument } from './vor-fixtures';
import {
  useCadVorCoverage,
  useCadVorDocuments,
  useCadVorLinks,
  useDeleteCadVor,
  usePutCadVorLinks,
  useImportCadVorFromRevision,
  useCadVorSources,
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
      importRevision: useImportCadVorFromRevision('p1'),
      sources: useCadVorSources('p1', true),
      remove: useDeleteCadVor('p1'),
      put: usePutCadVorLinks('p1'),
    }),
    { wrapper },
  );
};

describe('запросы ВОР', () => {
  beforeEach(() => {
    for (const mock of Object.values(mocks)) mock.mockReset();
    mocks.docs.mockResolvedValue({ data: [vorDocument()] });
    mocks.links.mockResolvedValue({ data: [] });
    mocks.coverage.mockResolvedValue({ data: coverage() });
    mocks.importRevision.mockResolvedValue({ data: vorDocument({ id: 'd2' }) });
    mocks.projectDocs.mockResolvedValue({
      data: {
        items: [
          { id: 'doc1', display_name: 'ВОР.xlsx' },
          { id: 'doc2', display_name: 'чертёж.pdf' },
          { id: 'doc3', display_name: 'Книга.xlsx' },
        ],
      },
    });
    mocks.projectRevisions.mockResolvedValue({
      data: [
        { id: 'rev-old', document_id: 'doc1', source_filename: 'ВОР.xlsx', source_sha256: 'old' },
        { id: 'rev-new', document_id: 'doc1', source_filename: 'ВОР.xlsx', source_sha256: 'new' },
        { id: 'rev3', document_id: 'doc3', source_filename: 'Книга.pdf', source_sha256: 'pdf' },
      ],
    });
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

  it('импорт из ревизии: тело с id ревизии, список, связи и сверка перечитываются', async () => {
    const { result } = await loaded();
    await act(async () => {
      await result.current.importRevision.mutateAsync({ revisionId: 'rev-new' });
    });
    expect(mocks.importRevision).toHaveBeenCalledWith({
      throwOnError: true,
      path: { project_id: 'p1' },
      body: { revision_id: 'rev-new' },
    });
    await waitFor(() => expect(calls()).toEqual([2, 2, 2]));
  });

  it('замена: прежние документы удаляются после импорта нового', async () => {
    const { result } = await loaded();
    await act(async () => {
      await result.current.importRevision.mutateAsync({ revisionId: 'rev-new', replaceIds: ['d1'] });
    });
    expect(mocks.remove).toHaveBeenCalledWith({
      throwOnError: true,
      path: { project_id: 'p1', document_id: 'd1' },
    });
    expect(mocks.importRevision.mock.invocationCallOrder[0]).toBeLessThan(
      mocks.remove.mock.invocationCallOrder[0] ?? 0,
    );
  });

  it('источники: книги .xlsx проекта, последняя ревизия; не .xlsx отбрасываются', async () => {
    const { result } = mount();
    await waitFor(() => expect(result.current.sources.sources).toHaveLength(1));
    expect(result.current.sources.sources).toEqual([
      { documentId: 'doc1', revisionId: 'rev-new', fileName: 'ВОР.xlsx', sha256: 'new' },
    ]);
    expect(mocks.projectRevisions).toHaveBeenCalledTimes(1);
    expect(mocks.projectRevisions).toHaveBeenCalledWith({
      throwOnError: true,
      path: { project_id: 'p1' },
    });
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
});
