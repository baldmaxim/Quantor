'use client';

import { createCadFloor3dDxf, readJob, type CadWallsJobRead, type JobRead } from '@quantor/api-client';
import { useQuery } from '@tanstack/react-query';
import { useCallback, useState } from 'react';

import { extractCode } from '@/lib/errors';
import { unwrap } from '@/lib/queries';

import { cadArtifactUrl } from './artifacts';
import { cadErrorText } from './errors';
import { WALLS_POLL_MS } from './constructions-queries';
import { viewFolder } from './mep-candidate';
import type { ICadViewParams } from './view-queries';

/**
 * Выгрузка 3D-модели этажа в 3D DXF (ADR-0039): задание `cad_floor3d_dxf`. Повтор с той же моделью
 * сервер отдаёт тем же заданием, поэтому готовый результат держится в состоянии и новый POST до
 * смены модели не нужен. Статус - общий `GET /jobs/{id}` с тем же периодом опроса, что у конструкций.
 */

export type Floor3dDxfPhase = 'idle' | 'preparing' | 'ready' | 'failed';

export interface IFloor3dDxf {
  readonly phase: Floor3dDxfPhase;
  /** Адрес файла готового DXF; пока файла нет - `null`. */
  readonly url: string | null;
  /** Имя скачиваемого файла. */
  readonly fileName: string;
  /** Текст отказа для `failed`. */
  readonly error: string | null;
  /** Идентификатор задания, чей файл уже готов (для однократного автоскачивания). */
  readonly readyJobId: string | null;
  readonly start: () => void;
}

const isActive = (status: string | undefined): boolean => status === 'queued' || status === 'running';

const jobFailureText = (job: JobRead): string => {
  const code = job.error_code;
  if (code) return cadErrorText({ detail: { code, message: job.error_message ?? undefined } });
  return job.status === 'cancelled' ? 'Задание выгрузки отменено.' : 'Не удалось подготовить DXF.';
};

/**
 * `resetKey` - то, от чего зависит DXF (модель этажа): при смене результат сбрасывается и
 * следующее нажатие ставит задание заново.
 */
export const useFloor3dDxf = (params: ICadViewParams, resetKey: unknown): IFloor3dDxf => {
  // Результат привязан к модели, для которой поставлено задание: у новой модели он не виден.
  const [result, setResult] = useState<{
    readonly key: unknown;
    readonly job: CadWallsJobRead | null;
    readonly failure: unknown;
  } | null>(null);
  const [pending, setPending] = useState(false);
  const own = result !== null && result.key === resetKey ? result : null;
  const posted = own?.job ?? null;

  const start = useCallback(() => {
    setPending(true);
    setResult(null);
    createCadFloor3dDxf({
      throwOnError: true,
      path: {
        project_id: params.projectId,
        job_id: params.jobId,
        page_index: params.pageIndex,
        view: params.view,
      },
    })
      .then((response) => setResult({ key: resetKey, job: unwrap(response), failure: null }))
      .catch((failure: unknown) => setResult({ key: resetKey, job: null, failure }))
      .finally(() => setPending(false));
  }, [params.projectId, params.jobId, params.pageIndex, params.view, resetKey]);

  const jobId = posted?.job_id ?? null;
  const poll = useQuery({
    queryKey: ['cad-floor3d-dxf-job', jobId],
    enabled: jobId !== null && isActive(posted?.status),
    queryFn: async () => unwrap(await readJob({ throwOnError: true, path: { job_id: jobId ?? '' } })),
    retry: (count, error) => extractCode(error) === 'NETWORK_ERROR' && count < 2,
    refetchInterval: (query) => (isActive(query.state.data?.status) ? WALLS_POLL_MS : false),
  });

  const status = poll.data?.status ?? posted?.status;
  const fileName = `floor3d_p${params.pageIndex + 1}_v${params.view}.dxf`;

  let phase: Floor3dDxfPhase = 'idle';
  let error: string | null = null;
  if (own !== null && own.failure !== null) {
    phase = 'failed';
    error = cadErrorText(own.failure);
  } else if (poll.isError && isActive(posted?.status)) {
    phase = 'failed';
    error = cadErrorText(poll.error);
  } else if (pending || (posted !== null && isActive(status))) {
    phase = 'preparing';
  } else if (status === 'succeeded') {
    phase = 'ready';
  } else if (posted !== null) {
    phase = 'failed';
    error = poll.data ? jobFailureText(poll.data) : 'Не удалось подготовить DXF.';
  }

  const readyJobId = phase === 'ready' ? jobId : null;
  const url =
    readyJobId === null
      ? null
      : cadArtifactUrl(
          params.projectId,
          params.revisionId,
          readyJobId,
          `${viewFolder(params.pageIndex, params.view)}/floor3d.dxf`,
        );

  return { phase, url, fileName, error, readyJobId, start };
};
