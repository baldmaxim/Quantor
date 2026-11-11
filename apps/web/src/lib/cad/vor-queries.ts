'use client';

import {
  deleteCadVorDocument,
  listCadVorDocuments,
  listCadVorItems,
  listCadVorLinks,
  putCadVorLinks,
  readCadVorCoverage,
  suggestCadVorItems,
  uploadCadVor,
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

import { extractCode } from '@/lib/errors';
import { unwrap } from '@/lib/queries';

import { cadErrorText } from './errors';
import { checkVorFile, VorFileError } from './vor';
import type { ICadViewParams } from './view-queries';

/**
 * ВОР Заказчика: запросы и мутации (ADR-0038 п. 5). Все ключи лежат под `['cad-vor', projectId]`:
 * загрузка, удаление и смена связей инвалидируют этот префикс разом - список документов, связи,
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

export interface IUploadVor {
  readonly file: File;
  /** Прежние документы, которые заменяются: удаляются после успешной загрузки (со связями). */
  readonly replaceIds?: readonly string[];
}

/** Загрузка ВОР: multipart через клиент API, предел и тип файла проверяются до отправки. */
export const useUploadCadVor = (
  projectId: string | null,
): UseMutationResult<CadVorDocumentRead, unknown, IUploadVor> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ file, replaceIds = [] }) => {
      if (projectId === null) throw new Error('Проект не выбран');
      const problem = checkVorFile(file);
      if (problem !== null) throw new VorFileError(problem);
      const created = unwrap(
        await uploadCadVor({ throwOnError: true, path: { project_id: projectId }, body: { file } }),
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

/** Текст отказа: проверка файла до отправки, затем словарь CAD и сообщение сервера. */
export const vorErrorText = (error: unknown): string =>
  error instanceof VorFileError ? error.message : cadErrorText(error);
