'use client';

import {
  createTenderVersion,
  deleteTenderVersion,
  deleteTenderVersionDocument,
  freezeTenderVersion,
  listHubCandidates,
  listTenderVersions,
  putTenderVersionDocument,
  readTenderVersion,
  updateTenderVersion,
  type TenderVersionCreate,
  type TenderVersionDocumentPut,
  type TenderVersionSummaryRead,
  type TenderVersionUpdate,
} from '@quantor/api-client';
import { type Query, hashKey, useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { unwrap } from '@/lib/queries';

/**
 * Версии тендера (ADR-0035, этап M2): замороженные комплекты ревизий документов проекта.
 *
 * Возможность закрыта пилотным флагом `tender.versions` и на сервере, и здесь (ADR-0023).
 * Пока мета не пришла, решения нет: страница не должна ни показаться, ни ответить
 * «не найдено» раньше времени.
 */

export const TENDER_VERSIONS_FEATURE = 'tender.versions';

export type VersionsAccess = 'pending' | 'open' | 'hidden';

export const versionsAccess = (
  metaLoaded: boolean,
  features: Readonly<Record<string, boolean>>,
): VersionsAccess => {
  if (!metaLoaded) return 'pending';
  return features[TENDER_VERSIONS_FEATURE] === true ? 'open' : 'hidden';
};

/** Ключи с общим префиксом проекта: любое изменение версии сбрасывает список и карточку разом. */
export const versionKeys = {
  root: (projectId: string) => ['project', projectId, 'tender-versions'] as const,
  list: (projectId: string) => ['project', projectId, 'tender-versions', 'list'] as const,
  one: (projectId: string, versionId: string) =>
    ['project', projectId, 'tender-versions', 'one', versionId] as const,
  candidates: (projectId: string) =>
    ['project', projectId, 'tender-versions', 'hub-candidates'] as const,
};

/** Подпись версии в списке: «Версия 2» и, если задана, пользовательская подпись. */
export const versionTitle = (
  version: Pick<TenderVersionSummaryRead, 'number' | 'label'>,
): string =>
  version.label ? `Версия ${version.number} · ${version.label}` : `Версия ${version.number}`;

/** Какая версия открыта по умолчанию: черновик, а без него — самая новая. */
export const defaultVersionId = (
  versions: readonly Pick<TenderVersionSummaryRead, 'id' | 'number' | 'status'>[],
): string | null => {
  const draft = versions.find((version) => version.status === 'draft');
  if (draft) return draft.id;
  return (
    versions.reduce<(typeof versions)[number] | null>(
      (latest, version) => (latest === null || version.number > latest.number ? version : latest),
      null,
    )?.id ?? null
  );
};

/** Начало отпечатка комплекта: по нему версию узнают на глаз, полный хеш — в подсказке. */
export const HASH_PREVIEW_LENGTH = 12;

export const hashStart = (hash: string | null): string =>
  hash === null ? '—' : `${hash.slice(0, HASH_PREVIEW_LENGTH)}…`;

const DEADLINE = new Intl.DateTimeFormat('ru', { day: 'numeric', month: 'long', year: 'numeric' });

/** Срок подачи из HUBTender приходит строкой; нечитаемое значение показывается как есть. */
export const formatDeadline = (value: string | null): string => {
  if (value === null) return 'без срока';
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? value : DEADLINE.format(date);
};

export const useTenderVersions = (projectId: string, enabled: boolean) =>
  useQuery({
    queryKey: versionKeys.list(projectId),
    enabled,
    queryFn: async () =>
      unwrap(await listTenderVersions({ throwOnError: true, path: { project_id: projectId } })),
  });

export const useTenderVersion = (projectId: string, versionId: string | null) =>
  useQuery({
    queryKey: versionKeys.one(projectId, versionId ?? ''),
    enabled: versionId !== null,
    queryFn: async () =>
      unwrap(
        await readTenderVersion({
          throwOnError: true,
          path: { project_id: projectId, version_id: versionId ?? '' },
        }),
      ),
  });

export const useHubCandidates = (projectId: string, enabled: boolean) =>
  useQuery({
    queryKey: versionKeys.candidates(projectId),
    enabled,
    queryFn: async () =>
      unwrap(await listHubCandidates({ throwOnError: true, path: { project_id: projectId } })),
  });

/** Каждая правка сбрасывает всё дерево версий проекта: список показывает число документов. */
const useInvalidateVersions = (projectId: string) => {
  const queryClient = useQueryClient();
  return () => queryClient.invalidateQueries({ queryKey: versionKeys.root(projectId) });
};

export const useCreateTenderVersion = (projectId: string) => {
  const invalidate = useInvalidateVersions(projectId);
  return useMutation({
    mutationFn: async (body: TenderVersionCreate) =>
      unwrap(
        await createTenderVersion({ throwOnError: true, path: { project_id: projectId }, body }),
      ),
    onSuccess: invalidate,
  });
};

export const useUpdateTenderVersion = (projectId: string, versionId: string) => {
  const invalidate = useInvalidateVersions(projectId);
  return useMutation({
    mutationFn: async (body: TenderVersionUpdate) =>
      unwrap(
        await updateTenderVersion({
          throwOnError: true,
          path: { project_id: projectId, version_id: versionId },
          body,
        }),
      ),
    onSuccess: invalidate,
  });
};

/**
 * Что сбрасывать после удаления версии. Карточка удалённой версии ещё на экране, пока не пришёл
 * новый список: её перезапрос ответил бы 404.
 */
export const invalidationAfterDelete = (projectId: string, versionId: string) => {
  const deleted = hashKey(versionKeys.one(projectId, versionId));
  return {
    queryKey: versionKeys.root(projectId),
    predicate: (query: Query) => query.queryHash !== deleted,
  };
};

export const useDeleteTenderVersion = (projectId: string, versionId: string) => {
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: async () => {
      await deleteTenderVersion({
        throwOnError: true,
        path: { project_id: projectId, version_id: versionId },
      });
    },
    onSuccess: () => queryClient.invalidateQueries(invalidationAfterDelete(projectId, versionId)),
  });
};

export const useFreezeTenderVersion = (projectId: string, versionId: string) => {
  const invalidate = useInvalidateVersions(projectId);
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await freezeTenderVersion({
          throwOnError: true,
          path: { project_id: projectId, version_id: versionId },
        }),
      ),
    onSuccess: invalidate,
  });
};

export interface PutDocumentInput {
  readonly documentId: string;
  readonly body: TenderVersionDocumentPut;
}

export const usePutVersionDocument = (projectId: string, versionId: string) => {
  const invalidate = useInvalidateVersions(projectId);
  return useMutation({
    mutationFn: async ({ documentId, body }: PutDocumentInput) =>
      unwrap(
        await putTenderVersionDocument({
          throwOnError: true,
          path: { project_id: projectId, version_id: versionId, document_id: documentId },
          body,
        }),
      ),
    onSuccess: invalidate,
  });
};

export const useRemoveVersionDocument = (projectId: string, versionId: string) => {
  const invalidate = useInvalidateVersions(projectId);
  return useMutation({
    mutationFn: async (documentId: string) => {
      await deleteTenderVersionDocument({
        throwOnError: true,
        path: { project_id: projectId, version_id: versionId, document_id: documentId },
      });
    },
    onSuccess: invalidate,
  });
};
