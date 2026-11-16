'use client';

import {
  createStylePreview,
  createStyleVersionFromPreview,
  getStylePreview,
  getStyleProfile,
  type CadStylePreviewRead,
  type CadStyleProfileRead,
  type CadStyleVersionRead,
  type CadStyleSample,
} from '@quantor/api-client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { extractCode } from '@/lib/errors';
import { unwrap } from '@/lib/queries';

import { isActiveStatus } from './queries';

/**
 * Профиль оформления тома (флаг `cad.export`, ADR-0049): текущая версия, предпросмотр по образцам
 * и принятие. Профиль принадлежит документу (тому), а не ревизии.
 */

export const STYLE_PREVIEW_POLL_MS = 1500;

export const styleKeys = {
  profile: (projectId: string, documentId: string) =>
    ['cad', projectId, documentId, 'style-profile'] as const,
  preview: (projectId: string, documentId: string, jobId: string) =>
    ['cad', projectId, documentId, 'style-preview', jobId] as const,
};

/** Профиль тома; `null` - профиля нет (404): движок выбирает оформление сам. */
export const useStyleProfile = (
  projectId: string,
  documentId: string | null,
  enabled: boolean,
): UseQueryResult<CadStyleProfileRead | null> =>
  useQuery({
    queryKey: styleKeys.profile(projectId, documentId ?? ''),
    enabled: enabled && documentId !== null,
    queryFn: async () => {
      try {
        return unwrap(
          await getStyleProfile({
            throwOnError: true,
            path: { project_id: projectId, document_id: documentId ?? '' },
          }),
        );
      } catch (error) {
        if (extractCode(error) === 'NOT_FOUND') return null;
        throw error;
      }
    },
    retry: (count, error) => extractCode(error) === 'NETWORK_ERROR' && count < 2,
  });

export interface IStylePreviewRequest {
  readonly revisionId: string;
  readonly pageIndex: number;
  readonly samples: readonly CadStyleSample[];
}

/** Поставить предпросмотр: ответ - идентификатор задания, которое затем опрашивается. */
export const useCreateStylePreview = (
  projectId: string,
  documentId: string | null,
): UseMutationResult<string, unknown, IStylePreviewRequest> =>
  useMutation({
    mutationFn: async ({ revisionId, pageIndex, samples }) =>
      unwrap(
        await createStylePreview({
          throwOnError: true,
          path: { project_id: projectId, document_id: documentId ?? '' },
          body: { revision_id: revisionId, page_index: pageIndex, samples: [...samples] },
        }),
      ).job_id,
  });

/** Задание предпросмотра; пока оно идёт, ответ опрашивается. */
export const useStylePreviewJob = (
  projectId: string,
  documentId: string | null,
  jobId: string | null,
): UseQueryResult<CadStylePreviewRead> =>
  useQuery({
    queryKey: styleKeys.preview(projectId, documentId ?? '', jobId ?? ''),
    enabled: documentId !== null && jobId !== null,
    queryFn: async () =>
      unwrap(
        await getStylePreview({
          throwOnError: true,
          path: {
            project_id: projectId,
            document_id: documentId ?? '',
            job_id: jobId ?? '',
          },
        }),
      ),
    refetchInterval: (query) =>
      isActiveStatus(query.state.data?.status) ? STYLE_PREVIEW_POLL_MS : false,
    retry: (count, error) => extractCode(error) === 'NETWORK_ERROR' && count < 2,
  });

export interface IAcceptStylePreview {
  readonly jobId: string;
  readonly title: string | null;
  /** Номер текущей версии профиля; `null` - профиля ещё нет. */
  readonly expectedCurrentVersion: number | null;
}

/** Принять предпросмотр: создаёт новую версию профиля; профиль перечитывается. */
export const useAcceptStylePreview = (
  projectId: string,
  documentId: string | null,
): UseMutationResult<CadStyleVersionRead, unknown, IAcceptStylePreview> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ jobId, title, expectedCurrentVersion }) =>
      unwrap(
        await createStyleVersionFromPreview({
          throwOnError: true,
          path: { project_id: projectId, document_id: documentId ?? '' },
          body: {
            job_id: jobId,
            title: title === null || title.trim() === '' ? null : title.trim(),
            expected_current_version: expectedCurrentVersion,
          },
        }),
      ),
    // При конфликте профиль тоже перечитывается: следующий предпросмотр берёт свежую версию.
    onSettled: () =>
      client.invalidateQueries({ queryKey: styleKeys.profile(projectId, documentId ?? '') }),
  });
};
