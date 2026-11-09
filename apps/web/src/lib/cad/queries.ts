'use client';

import {
  createCadJob,
  deleteCadRemark,
  importCadRemarks,
  listCadJobs,
  listCadRemarks,
  putCadRemark,
  readCadEvents,
  readCadJob,
  retryCadJob,
  type CadJobListRead,
  type CadJobRead,
  type CadRemarkRead,
  type CadRemarksFile,
  type CadRemarksImportRead,
  type CadRemarkWrite,
} from '@quantor/api-client';
import {
  useMutation,
  useQuery,
  useQueryClient,
  type UseMutationResult,
  type UseQueryResult,
} from '@tanstack/react-query';
import { useEffect, useMemo, useRef } from 'react';

import { unwrap } from '@/lib/queries';

import { emptyEventLog, isEventLogComplete, mergeEvents, type ICadEventLog } from './events';
import { sortRemarks, type IRemarkBinding } from './remarks';

/**
 * Обращения к CAD-заданиям (QA-контур, флаг `cad.export`).
 *
 * Ключи содержат проект, ревизию, задание и попытку: ответ прежнего документа не может
 * оказаться на экране нового. Ключ задания не является началом ключа событий — обновление
 * задания не сбрасывает накопленный журнал.
 */

export const cadKeys = {
  jobs: (projectId: string, revisionId: string) => ['cad', projectId, revisionId, 'jobs'] as const,
  job: (projectId: string, revisionId: string, jobId: string) =>
    ['cad', projectId, revisionId, 'job', jobId, 'detail'] as const,
  events: (projectId: string, revisionId: string, jobId: string, attempt: number) =>
    ['cad', projectId, revisionId, 'job', jobId, 'events', attempt] as const,
  remarks: (binding: IRemarkBinding) =>
    [
      'cad',
      binding.projectId,
      binding.revisionId,
      'job',
      binding.jobId,
      'remarks',
      binding.attempt,
      binding.pageIndex,
      binding.view,
    ] as const,
};

const POLL_INTERVAL = 2000;

export const isActiveStatus = (status: string | null | undefined): boolean =>
  status === 'queued' || status === 'running';

export const useCadJobs = (
  projectId: string,
  revisionId: string | null,
): UseQueryResult<CadJobListRead> =>
  useQuery({
    queryKey: cadKeys.jobs(projectId, revisionId ?? ''),
    enabled: revisionId !== null,
    queryFn: async () =>
      unwrap(
        await listCadJobs({
          throwOnError: true,
          path: { project_id: projectId, revision_id: revisionId ?? '' },
        }),
      ),
    refetchInterval: (query) =>
      query.state.data?.items.some((item) => isActiveStatus(item.status)) ? POLL_INTERVAL : false,
  });

export const useCadJob = (
  projectId: string,
  revisionId: string | null,
  jobId: string | null,
): UseQueryResult<CadJobRead> =>
  useQuery({
    queryKey: cadKeys.job(projectId, revisionId ?? '', jobId ?? ''),
    enabled: revisionId !== null && jobId !== null,
    queryFn: async () => {
      const job = unwrap(
        await readCadJob({
          throwOnError: true,
          path: {
            project_id: projectId,
            revision_id: revisionId ?? '',
            job_id: jobId ?? '',
          },
        }),
      );
      // Ответ чужого задания не показываем: защита сверх ключа запроса.
      if (job.job_id !== jobId || job.revision_id !== revisionId) {
        throw new Error('Ответ не относится к выбранному заданию');
      }
      return job;
    },
    refetchInterval: (query) => (isActiveStatus(query.state.data?.status) ? POLL_INTERVAL : false),
  });

/**
 * Журнал событий попытки с накоплением.
 *
 * Каждый запрос идёт с `after_seq` = последнего принятого номера; в журнал попадают только
 * новые события. `live` — попытка ещё идёт: опрос продолжается, пока она идёт или пока
 * получены не все события, о которых сообщил сервер.
 */
export const useCadEvents = (
  projectId: string,
  revisionId: string | null,
  jobId: string | null,
  attempt: number | null,
  live: boolean,
): UseQueryResult<ICadEventLog> => {
  const client = useQueryClient();
  const enabled = revisionId !== null && jobId !== null && attempt !== null;
  const key = useMemo(
    () => cadKeys.events(projectId, revisionId ?? '', jobId ?? '', attempt ?? 0),
    [projectId, revisionId, jobId, attempt],
  );

  // Когда попытка перестала идти, события последних секунд ещё могли не дойти: один
  // добор по тому же курсору.
  const wasLive = useRef(live);
  useEffect(() => {
    if (wasLive.current && !live && enabled) {
      void client.invalidateQueries({ queryKey: key, exact: true });
    }
    wasLive.current = live;
  }, [live, enabled, client, key]);

  return useQuery({
    queryKey: key,
    enabled,
    // Журнал накапливается в данных запроса, поэтому его нельзя выбрасывать как устаревший.
    gcTime: 5 * 60_000,
    queryFn: async () => {
      const current = jobId ?? '';
      const number = attempt ?? 0;
      const known = client.getQueryData<ICadEventLog>(key) ?? emptyEventLog(current, number);
      const response = unwrap(
        await readCadEvents({
          throwOnError: true,
          path: {
            project_id: projectId,
            revision_id: revisionId ?? '',
            job_id: current,
          },
          query: { attempt: number, after_seq: known.lastSeq },
        }),
      );
      return mergeEvents(known, response);
    },
    refetchInterval: (query) =>
      live || (query.state.data !== undefined && !isEventLogComplete(query.state.data))
        ? POLL_INTERVAL
        : false,
  });
};

interface ICreateCadJobInput {
  /** Индексы страниц PDF с 0; `null` — страницы, выбранные движком. */
  readonly pages: readonly number[] | null;
}

/** Создаёт задание. Если такое уже идёт, сервер возвращает его же — дубля нет. */
export const useCreateCadJob = (
  projectId: string,
  revisionId: string,
): UseMutationResult<CadJobRead, unknown, ICreateCadJobInput> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ pages }) =>
      unwrap(
        await createCadJob({
          throwOnError: true,
          path: { project_id: projectId, revision_id: revisionId },
          body: { pages: pages === null ? null : [...pages], finishes: false, schedules: false },
        }),
      ),
    onSuccess: (job) => {
      client.setQueryData(cadKeys.job(projectId, revisionId, job.job_id), job);
      void client.invalidateQueries({ queryKey: cadKeys.jobs(projectId, revisionId) });
    },
  });
};

/** Повтор задания: новая попытка того же задания. */
export const useRetryCadJob = (
  projectId: string,
  revisionId: string,
  jobId: string,
): UseMutationResult<CadJobRead, unknown, void> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async () =>
      unwrap(
        await retryCadJob({
          throwOnError: true,
          path: { project_id: projectId, revision_id: revisionId, job_id: jobId },
        }),
      ),
    onSuccess: (job) => {
      client.setQueryData(cadKeys.job(projectId, revisionId, jobId), job);
      void client.invalidateQueries({ queryKey: cadKeys.job(projectId, revisionId, jobId) });
      void client.invalidateQueries({ queryKey: cadKeys.jobs(projectId, revisionId) });
    },
  });
};

/**
 * Запуск преобразования для ревизии: если у неё уже есть задание — выбирается идущее или
 * последнее, иначе создаётся новое со страницами по выбору движка. Возвращает идентификатор
 * задания.
 */
export const useStartCadJob = (
  projectId: string,
): UseMutationResult<string, unknown, { revisionId: string }> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async ({ revisionId }) => {
      const list = await client.fetchQuery({
        queryKey: cadKeys.jobs(projectId, revisionId),
        staleTime: 0,
        queryFn: async () =>
          unwrap(
            await listCadJobs({
              throwOnError: true,
              path: { project_id: projectId, revision_id: revisionId },
            }),
          ),
      });
      // Идущее задание важнее; иначе — последнее завершённое: выбор ревизии с историей
      // показывает её, а не ставит тот же детерминированный прогон ещё раз.
      const existing = list.items.find((item) => isActiveStatus(item.status)) ?? list.items[0];
      if (existing) {
        return existing.job_id;
      }
      const job = unwrap(
        await createCadJob({
          throwOnError: true,
          path: { project_id: projectId, revision_id: revisionId },
          body: { pages: null, finishes: false, schedules: false },
        }),
      );
      client.setQueryData(cadKeys.job(projectId, revisionId, job.job_id), job);
      return job.job_id;
    },
    onSuccess: (_jobId, { revisionId }) => {
      void client.invalidateQueries({ queryKey: cadKeys.jobs(projectId, revisionId) });
    },
  });
};

// ---------------------------------------------------------------- замечания проверяющего

const remarkPath = (binding: IRemarkBinding) => ({
  project_id: binding.projectId,
  revision_id: binding.revisionId,
  job_id: binding.jobId,
});

const remarkQuery = (binding: IRemarkBinding) => ({
  attempt: binding.attempt,
  page_index: binding.pageIndex,
  view: binding.view,
});

/** Замечания вида и попытки с сервера в порядке номеров. */
export const useCadRemarksList = (binding: IRemarkBinding): UseQueryResult<CadRemarkRead[]> =>
  useQuery({
    queryKey: cadKeys.remarks(binding),
    queryFn: async () =>
      sortRemarks(
        unwrap(
          await listCadRemarks({
            throwOnError: true,
            path: remarkPath(binding),
            query: remarkQuery(binding),
          }),
        ),
      ),
  });

interface ISaveCadRemarkInput {
  /** Клиентский идентификатор замечания (`remark_key`). */
  readonly id: string;
  readonly body: CadRemarkWrite;
}

/** Создание или изменение замечания: один запрос, повтор того же `id` обновляет. */
export const useSaveCadRemark = (
  binding: IRemarkBinding,
): UseMutationResult<CadRemarkRead, unknown, ISaveCadRemarkInput> => {
  const client = useQueryClient();
  const key = cadKeys.remarks(binding);
  return useMutation({
    mutationFn: async ({ id, body }) =>
      unwrap(
        await putCadRemark({
          throwOnError: true,
          path: { ...remarkPath(binding), remark_key: id },
          query: remarkQuery(binding),
          body,
        }),
      ),
    onSuccess: (saved) => {
      client.setQueryData<CadRemarkRead[]>(key, (current = []) =>
        sortRemarks([...current.filter((item) => item.id !== saved.id), saved]),
      );
    },
    // Список сверяется с сервером и после отказа: правка могла пройти или не дойти.
    onSettled: () => client.invalidateQueries({ queryKey: key }),
  });
};

/** Удаление замечания по `id`. */
export const useDeleteCadRemark = (
  binding: IRemarkBinding,
): UseMutationResult<void, unknown, string> => {
  const client = useQueryClient();
  const key = cadKeys.remarks(binding);
  return useMutation({
    mutationFn: async (id) => {
      await deleteCadRemark({
        throwOnError: true,
        path: { ...remarkPath(binding), remark_key: id },
        query: remarkQuery(binding),
      });
    },
    onSuccess: (_data, id) => {
      client.setQueryData<CadRemarkRead[]>(key, (current = []) =>
        current.filter((item) => item.id !== id),
      );
    },
    onSettled: () => client.invalidateQueries({ queryKey: key }),
  });
};

/** Импорт файла `quantor.cad-remarks.v1`: слияние делает сервер, ответ - число новых и обновлённых. */
export const useImportCadRemarks = (
  binding: IRemarkBinding,
): UseMutationResult<CadRemarksImportRead, unknown, CadRemarksFile> => {
  const client = useQueryClient();
  return useMutation({
    mutationFn: async (file) =>
      unwrap(
        await importCadRemarks({
          throwOnError: true,
          path: remarkPath(binding),
          body: file,
        }),
      ),
    onSettled: () => client.invalidateQueries({ queryKey: cadKeys.remarks(binding) }),
  });
};
