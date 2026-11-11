'use client';

import {
  assignCadFinishTemplate,
  createCadFinishTemplate,
  deleteCadFinishTemplate,
  listCadFinishTemplates,
  readCadFinishes,
  updateCadFinishTemplate,
  type CadFinishAssignResult,
  type CadFinishSheetRead,
  type CadFinishTemplatePatch,
  type CadFinishTemplateRead,
  type CadFinishTemplateWrite,
} from '@quantor/api-client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { unwrap } from '@/lib/queries';

/**
 * Отделка помещений в пилоте CAD (ADR-0042, флаг `cad.export`): шаблоны проекта, назначение зонам
 * и ведомость листа. Ведомость считает сервер при чтении, поэтому любая запись шаблонов, зон или
 * назначений её перечитывает. Ключи начинаются как ключи зон (`['cad', проект, ревизия, ...]`).
 */

export const finishKeys = {
  templates: (projectId: string) => ['cad-finish-templates', projectId] as const,
  sheet: (projectId: string, revisionId: string, pageIndex: number) =>
    ['cad', projectId, revisionId, 'finishes', pageIndex] as const,
  /** Все ведомости ревизии: после правки зон любого листа. */
  revision: (projectId: string, revisionId: string) =>
    ['cad', projectId, revisionId, 'finishes'] as const,
};

/** Перечитать ведомости ревизии: площади и итоги зависят от зон. */
export const invalidateFinishSheets = (
  client: QueryClient,
  projectId: string,
  revisionId: string,
): Promise<void> =>
  client.invalidateQueries({ queryKey: finishKeys.revision(projectId, revisionId) });

/** Перечитать зоны и ведомости проекта: шаблон мог измениться или быть удалён. */
const invalidateProjectFinishData = (client: QueryClient, projectId: string): Promise<void> =>
  client.invalidateQueries({
    predicate: ({ queryKey }) =>
      queryKey[0] === 'cad' &&
      queryKey[1] === projectId &&
      (queryKey[3] === 'zones' || queryKey[3] === 'finishes'),
  });

/** После записи шаблона: список шаблонов, зоны (ссылка на шаблон) и ведомости. */
const invalidateTemplateChange = async (client: QueryClient, projectId: string): Promise<void> => {
  await Promise.all([
    client.invalidateQueries({ queryKey: finishKeys.templates(projectId) }),
    invalidateProjectFinishData(client, projectId),
  ]);
};

export const useCadFinishTemplates = (
  projectId: string,
  enabled: boolean,
): UseQueryResult<CadFinishTemplateRead[]> =>
  useQuery({
    queryKey: finishKeys.templates(projectId),
    enabled,
    queryFn: async () =>
      unwrap(
        await listCadFinishTemplates({
          throwOnError: true,
          path: { project_id: projectId },
        }),
      ),
  });

export const useCadFinishSheet = (
  projectId: string,
  revisionId: string | null,
  pageIndex: number | null,
  enabled: boolean,
): UseQueryResult<CadFinishSheetRead> =>
  useQuery({
    queryKey: finishKeys.sheet(projectId, revisionId ?? '', pageIndex ?? -1),
    enabled: enabled && revisionId !== null && pageIndex !== null,
    queryFn: async () =>
      unwrap(
        await readCadFinishes({
          throwOnError: true,
          path: { project_id: projectId, revision_id: revisionId ?? '' },
          query: { page_index: pageIndex ?? 0 },
        }),
      ),
  });

export const useCreateCadFinishTemplate = (
  projectId: string,
): UseMutationResult<CadFinishTemplateRead, unknown, CadFinishTemplateWrite> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body) =>
      unwrap(
        await createCadFinishTemplate({
          throwOnError: true,
          path: { project_id: projectId },
          body,
        }),
      ),
    onSuccess: () => invalidateTemplateChange(client, projectId),
  });
};

interface IPatchTemplate {
  readonly id: string;
  readonly patch: CadFinishTemplatePatch;
}

export const useUpdateCadFinishTemplate = (
  projectId: string,
): UseMutationResult<CadFinishTemplateRead, unknown, IPatchTemplate> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ id, patch }) =>
      unwrap(
        await updateCadFinishTemplate({
          throwOnError: true,
          path: { project_id: projectId, template_id: id },
          body: patch,
        }),
      ),
    onSuccess: () => invalidateTemplateChange(client, projectId),
  });
};

export const useDeleteCadFinishTemplate = (
  projectId: string,
): UseMutationResult<unknown, unknown, string> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (id) =>
      deleteCadFinishTemplate({
        throwOnError: true,
        path: { project_id: projectId, template_id: id },
      }),
    onSuccess: () => invalidateTemplateChange(client, projectId),
  });
};

interface IAssign {
  readonly zoneIds: readonly string[];
  /** `null` снимает явное назначение: зона снова получает шаблон по типу помещения. */
  readonly templateId: string | null;
}

export const useAssignCadFinishTemplate = (
  projectId: string,
): UseMutationResult<CadFinishAssignResult, unknown, IAssign> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ zoneIds, templateId }) =>
      unwrap(
        await assignCadFinishTemplate({
          throwOnError: true,
          path: { project_id: projectId },
          body: { zone_ids: [...zoneIds], template_id: templateId },
        }),
      ),
    onSuccess: () => invalidateProjectFinishData(client, projectId),
  });
};
