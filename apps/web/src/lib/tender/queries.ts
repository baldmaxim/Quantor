'use client';

import {
  createPersonalToken,
  createTenderBaseRelease,
  listPersonalTokens,
  listTenderBaseCandidates,
  listTenderBaseReleases,
  listTenderCalcVersions,
  listTenderCalcs,
  readTenderCalcVersion,
  revokePersonalToken,
  revokeTenderBaseRelease,
  withdrawTenderCalcVersion,
  type PersonalTokenCreate,
  type PersonalTokenCreated,
  type PersonalTokenRead,
  type TenderBaseCandidatesRead,
  type TenderBaseReleaseCreate,
  type TenderBaseReleaseRead,
  type TenderCalcVersionRead,
  type TenderCalcVersionSummaryRead,
  type TenderCalcVersionsRead,
  type TenderCalcsRead,
} from '@quantor/api-client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';

import { env } from '@/lib/env';
import { unwrap } from '@/lib/queries';

/**
 * Запросы страницы «Расчёты» (ADR-0051, флаг `tender.exchange`): репозитории расчётов и их версии,
 * выпуски базы объекта, личные токены. Тяжёлого опроса нет: данные меняет человек или внешний навык,
 * обновление — при возврате на вкладку и после своих действий.
 */

export const tenderKeys = {
  all: (projectId: string) => ['tender', projectId] as const,
  calcs: (projectId: string) => ['tender', projectId, 'calcs'] as const,
  versions: (projectId: string, calcId: string) =>
    ['tender', projectId, 'calcs', calcId, 'versions'] as const,
  version: (projectId: string, versionId: string) =>
    ['tender', projectId, 'version', versionId] as const,
  releases: (projectId: string) => ['tender', projectId, 'releases'] as const,
  candidates: (projectId: string) => ['tender', projectId, 'candidates'] as const,
  tokens: ['tender', 'personal-tokens'] as const,
};

/* ------------------------------------------------------------------ скачивание */

const projectBase = (projectId: string): string =>
  `${env.apiBaseUrl}/api/v1/projects/${encodeURIComponent(projectId)}/tender`;

/** Ссылка на ZIP выпуска базы: скачивание браузером с cookie сеанса, без base64 в JSON. */
export const tenderBaseDownloadUrl = (projectId: string, releaseId: string): string =>
  `${projectBase(projectId)}/base/releases/${encodeURIComponent(releaseId)}/download`;

/** Ссылка на исходный ZIP версии расчёта. */
export const tenderCalcPackageUrl = (projectId: string, versionId: string): string =>
  `${projectBase(projectId)}/calc-versions/${encodeURIComponent(versionId)}/package`;

/* ---------------------------------------------------------------------- расчёты */

export const useTenderCalcs = (
  projectId: string,
  enabled: boolean,
): UseQueryResult<TenderCalcsRead> =>
  useQuery({
    queryKey: tenderKeys.calcs(projectId),
    enabled,
    queryFn: async () =>
      unwrap(await listTenderCalcs({ throwOnError: true, path: { project_id: projectId } })),
  });

export const useTenderCalcVersions = (
  projectId: string,
  calcId: string | null,
): UseQueryResult<TenderCalcVersionsRead> =>
  useQuery({
    queryKey: tenderKeys.versions(projectId, calcId ?? ''),
    enabled: calcId !== null,
    queryFn: async () =>
      unwrap(
        await listTenderCalcVersions({
          throwOnError: true,
          path: { project_id: projectId, calc_id: calcId ?? '' },
        }),
      ),
  });

export const useTenderCalcVersion = (
  projectId: string,
  versionId: string | null,
): UseQueryResult<TenderCalcVersionRead> =>
  useQuery({
    queryKey: tenderKeys.version(projectId, versionId ?? ''),
    enabled: versionId !== null,
    queryFn: async () =>
      unwrap(
        await readTenderCalcVersion({
          throwOnError: true,
          path: { project_id: projectId, version_id: versionId ?? '' },
        }),
      ),
  });

export const useWithdrawTenderVersion = (
  projectId: string,
): UseMutationResult<TenderCalcVersionSummaryRead, unknown, string> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (versionId) =>
      unwrap(
        await withdrawTenderCalcVersion({
          throwOnError: true,
          path: { project_id: projectId, version_id: versionId },
        }),
      ),
    // Отзыв может сделать действующей прежнюю версию: перечитываются и карточки, и история.
    onSuccess: () => client.invalidateQueries({ queryKey: tenderKeys.all(projectId) }),
  });
};

/* ------------------------------------------------------------------ база объекта */

export const useTenderBaseReleases = (
  projectId: string,
  enabled: boolean,
): UseQueryResult<TenderBaseReleaseRead[]> =>
  useQuery({
    queryKey: tenderKeys.releases(projectId),
    enabled,
    queryFn: async () =>
      unwrap(await listTenderBaseReleases({ throwOnError: true, path: { project_id: projectId } })),
  });

/** Кандидаты выпуска читаются при открытии окна: сервер собирает их по готовым видам здания. */
export const useTenderBaseCandidates = (
  projectId: string,
  enabled: boolean,
): UseQueryResult<TenderBaseCandidatesRead> =>
  useQuery({
    queryKey: tenderKeys.candidates(projectId),
    enabled,
    staleTime: 0,
    gcTime: 0,
    queryFn: async () =>
      unwrap(
        await listTenderBaseCandidates({ throwOnError: true, path: { project_id: projectId } }),
      ),
  });

export const useCreateTenderBaseRelease = (
  projectId: string,
): UseMutationResult<TenderBaseReleaseRead, unknown, TenderBaseReleaseCreate> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body) =>
      unwrap(
        await createTenderBaseRelease({
          throwOnError: true,
          path: { project_id: projectId },
          body,
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: tenderKeys.releases(projectId) }),
  });
};

export const useRevokeTenderBaseRelease = (
  projectId: string,
): UseMutationResult<TenderBaseReleaseRead, unknown, string> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (releaseId) =>
      unwrap(
        await revokeTenderBaseRelease({
          throwOnError: true,
          path: { project_id: projectId, release_id: releaseId },
        }),
      ),
    onSuccess: () => client.invalidateQueries({ queryKey: tenderKeys.releases(projectId) }),
  });
};

/* --------------------------------------------------------------- личные токены */

export const usePersonalTokens = (enabled: boolean): UseQueryResult<PersonalTokenRead[]> =>
  useQuery({
    queryKey: tenderKeys.tokens,
    enabled,
    queryFn: async () => unwrap(await listPersonalTokens({ throwOnError: true })),
  });

export const useCreatePersonalToken = (): UseMutationResult<
  PersonalTokenCreated,
  unknown,
  PersonalTokenCreate
> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (body) => unwrap(await createPersonalToken({ throwOnError: true, body })),
    onSuccess: () => client.invalidateQueries({ queryKey: tenderKeys.tokens }),
  });
};

export const useRevokePersonalToken = (): UseMutationResult<unknown, unknown, string> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (tokenId) => {
      await revokePersonalToken({ throwOnError: true, path: { token_id: tokenId } });
    },
    onSuccess: () => client.invalidateQueries({ queryKey: tenderKeys.tokens }),
  });
};
