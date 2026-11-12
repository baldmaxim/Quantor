'use client';

import {
  deleteCadVorDocument,
  importCadVorFromRevision,
  listCadVorDocuments,
  listCadVorItems,
  listCadVorLinks,
  putCadVorLinks,
  readCadVorCoverage,
  suggestCadVorItems,
  type CadVorCoverageRead,
  type CadVorDocumentRead,
  type CadVorItemRead,
  type CadVorItemsRead,
  type CadVorLinkRead,
  type CadVorSuggestionRead,
} from '@quantor/api-client';
import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { fileExtension } from '@/lib/documentSections';
import { extractCode } from '@/lib/errors';
import { unwrap, useProjectDocuments, useProjectRevisions } from '@/lib/queries';

import { cadErrorText } from './errors';
import type { ICadViewParams } from './view-queries';

/**
 * ВОР Заказчика: запросы и мутации (ADR-0038 п. 5). Все ключи лежат под `['cad-vor', projectId]`:
 * импорт, удаление и смена связей инвалидируют этот префикс разом - список документов, связи,
 * строки, подсказки и сверку листа. ВОР - только объект сверки, на подсчёт конструкций не влияет.
 */

export const vorKeys = {
  all: (projectId: string) => ['cad-vor', projectId] as const,
  documents: (projectId: string) => ['cad-vor', projectId, 'documents'] as const,
  links: (projectId: string) => ['cad-vor', projectId, 'links'] as const,
  items: (projectId: string, documentId: string, filter: IVorItemsFilter) =>
    ['cad-vor', projectId, 'items', documentId, filter.q, filter.kind, filter.thickness] as const,
  suggest: (projectId: string, groupKey: string, documentId: string | null) =>
    ['cad-vor', projectId, 'suggest', groupKey, documentId] as const,
  /** `stamp` - момент последнего чтения конструкций листа: сверка зависит от их параметров. */
  coverage: (params: ICadViewParams, stamp: number) =>
    ['cad-vor', params.projectId, 'coverage', params.jobId, params.pageIndex, params.view, stamp] as const,
};

export interface IVorItemsFilter {
  readonly q: string;
  readonly kind: 'masonry' | 'monolith' | null;
  readonly thickness: number | null;
}

/** Размер страницы строк в диалоге сопоставления. */
export const VOR_ITEMS_LIMIT = 50;

const retryNetworkOnly = (count: number, error: unknown): boolean =>
  extractCode(error) === 'NETWORK_ERROR' && count < 2;

/** Документы ВОР проекта; текущий - первый. */
export const useCadVorDocuments = (
  projectId: string | null,
  enabled: boolean,
): UseQueryResult<CadVorDocumentRead[], unknown> =>
  useQuery({
    queryKey: projectId ? vorKeys.documents(projectId) : ['cad-vor', 'idle', 'documents'],
    enabled: enabled && projectId !== null,
    queryFn: async () =>
      unwrap(await listCadVorDocuments({ throwOnError: true, path: { project_id: projectId ?? '' } })),
    retry: retryNetworkOnly,
  });

export const useCadVorLinks = (
  projectId: string | null,
  enabled: boolean,
): UseQueryResult<CadVorLinkRead[], unknown> =>
  useQuery({
    queryKey: projectId ? vorKeys.links(projectId) : ['cad-vor', 'idle', 'links'],
    enabled: enabled && projectId !== null,
    queryFn: async () =>
      unwrap(await listCadVorLinks({ throwOnError: true, path: { project_id: projectId ?? '' } })),
    retry: retryNetworkOnly,
  });

/** Сверка листа с ВОР. Прежний ответ держится на экране, пока читается новый. */
export const useCadVorCoverage = (
  params: ICadViewParams | null,
  enabled: boolean,
  stamp: number,
): UseQueryResult<CadVorCoverageRead, unknown> =>
  useQuery({
    queryKey: params ? vorKeys.coverage(params, stamp) : ['cad-vor', 'idle', 'coverage'],
    enabled: enabled && params !== null,
    placeholderData: keepPreviousData,
    queryFn: async () => {
      if (params === null) throw new Error('Вид листа не выбран');
      return unwrap(
        await readCadVorCoverage({
          throwOnError: true,
          path: {
            project_id: params.projectId,
            job_id: params.jobId,
            page_index: params.pageIndex,
            view: params.view,
          },
        }),
      );
    },
    retry: retryNetworkOnly,
  });

/** Строки документа ВОР: поиск по наименованию и фильтры (для диалога сопоставления). */
export const useCadVorItems = (
  projectId: string,
  documentId: string | null,
  filter: IVorItemsFilter,
  enabled: boolean,
): UseQueryResult<CadVorItemsRead, unknown> =>
  useQuery({
    queryKey: vorKeys.items(projectId, documentId ?? '', filter),
    enabled: enabled && documentId !== null,
    placeholderData: keepPreviousData,
    queryFn: async () =>
      unwrap(
        await listCadVorItems({
          throwOnError: true,
          path: { project_id: projectId, document_id: documentId ?? '' },
          query: {
            q: filter.q.trim() === '' ? undefined : filter.q.trim(),
            kind: filter.kind ?? undefined,
            thickness: filter.thickness ?? undefined,
            limit: VOR_ITEMS_LIMIT,
          },
        }),
      ),
    retry: retryNetworkOnly,
  });

/** Подсказки сервера для группы: строки-кандидаты с причинами; связь ставит человек. */
export const useCadVorSuggest = (
  projectId: string,
  groupKey: string,
  documentId: string | null,
  enabled: boolean,
): UseQueryResult<CadVorSuggestionRead[], unknown> =>
  useQuery({
    queryKey: vorKeys.suggest(projectId, groupKey, documentId),
    enabled,
    queryFn: async () =>
      unwrap(
        await suggestCadVorItems({
          throwOnError: true,
          path: { project_id: projectId },
          query: { group_key: groupKey, document_id: documentId ?? undefined },
        }),
      ),
    retry: retryNetworkOnly,
  });

/** Книга .xlsx из документов проекта: кандидат в ВОР Заказчика (последняя ревизия документа). */
export interface IVorSource {
  readonly documentId: string;
  readonly revisionId: string;
  readonly fileName: string;
  /** SHA-256 файла ревизии: по нему видно, какая книга сейчас стоит ВОРом. */
  readonly sha256: string;
}

export interface IVorSources {
  readonly sources: readonly IVorSource[];
  readonly loading: boolean;
  readonly error: unknown;
}

/**
 * Книги .xlsx документов проекта (вкладка «Документы»): последняя ревизия каждого документа, чьё
 * имя заканчивается на .xlsx. Ревизии идут от старой к новой, берётся последняя из прочитанных.
 */
export const useCadVorSources = (projectId: string | null, enabled: boolean): IVorSources => {
  const documents = useProjectDocuments(projectId ?? '', enabled && projectId !== null);
  const books = (documents.data?.items ?? []).filter(
    (document) => fileExtension(document.display_name) === 'xlsx',
  );
  const revisions = useProjectRevisions(
    projectId ?? '',
    books.map((document) => document.id),
    enabled && projectId !== null,
  );

  const sources: IVorSource[] = [];
  for (const document of books) {
    const items = revisions.byDocument.get(document.id)?.items ?? [];
    const latest = items[items.length - 1];
    if (latest !== undefined && fileExtension(latest.source_filename) === 'xlsx') {
      sources.push({
        documentId: document.id,
        revisionId: latest.id,
        fileName: latest.source_filename,
        sha256: latest.source_sha256,
      });
    }
  }
  return {
    sources,
    loading: documents.isPending || revisions.isPending,
    error: documents.isError ? documents.error : null,
  };
};

export interface IImportVorFromRevision {
  readonly revisionId: string;
  /** Прежние документы ВОР, которые заменяются: удаляются после успешного импорта (со связями). */
  readonly replaceIds?: readonly string[];
}

/** Импорт ВОР из ревизии документа проекта: сервер читает файл сам, берёт копию и разбирает. */
export const useImportCadVorFromRevision = (
  projectId: string | null,
): UseMutationResult<CadVorDocumentRead, unknown, IImportVorFromRevision> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ revisionId, replaceIds = [] }) => {
      if (projectId === null) throw new Error('Проект не выбран');
      const created = unwrap(
        await importCadVorFromRevision({
          throwOnError: true,
          path: { project_id: projectId },
          body: { revision_id: revisionId },
        }),
      );
      for (const id of replaceIds) {
        await deleteCadVorDocument({
          throwOnError: true,
          path: { project_id: projectId, document_id: id },
        });
      }
      return created;
    },
    onSettled: () => {
      if (projectId !== null) void client.invalidateQueries({ queryKey: vorKeys.all(projectId) });
    },
  });
};

export const useDeleteCadVor = (
  projectId: string | null,
): UseMutationResult<void, unknown, string> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (documentId) => {
      if (projectId === null) throw new Error('Проект не выбран');
      await deleteCadVorDocument({
        throwOnError: true,
        path: { project_id: projectId, document_id: documentId },
      });
    },
    onSettled: () => {
      if (projectId !== null) void client.invalidateQueries({ queryKey: vorKeys.all(projectId) });
    },
  });
};

export interface IPutVorLinks {
  readonly groupKey: string;
  readonly itemIds: readonly string[];
}

/** Полный набор строк ВОР группы: прежние связи группы заменяются. Пустой набор - «отвязать всё». */
export const usePutCadVorLinks = (
  projectId: string | null,
): UseMutationResult<CadVorItemRead[], unknown, IPutVorLinks> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ groupKey, itemIds }) => {
      if (projectId === null) throw new Error('Проект не выбран');
      return unwrap(
        await putCadVorLinks({
          throwOnError: true,
          path: { project_id: projectId, group_key: groupKey },
          body: { vor_item_ids: [...itemIds] },
        }),
      );
    },
    onSettled: () => {
      if (projectId !== null) void client.invalidateQueries({ queryKey: vorKeys.all(projectId) });
    },
  });
};

/** Текст отказа: словарь CAD и сообщение сервера. */
export const vorErrorText = (error: unknown): string => cadErrorText(error);
