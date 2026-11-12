import {
  createCadFloor3dDxf,
  createCadJob,
  recomputeCadWalls,
  retryCadJob,
  startCadZonesAuto,
} from '@quantor/api-client';

import { unwrap } from '@/lib/queries';

import type { IPipelineAction } from './pipeline-actions';

/**
 * Исполнение одного действия листа на сервере (без React): общий код кнопок строки листа и
 * массового запуска конвейера. Переходы и скачивания ничего не запускают.
 */

export interface IRunPipelineActionInput {
  readonly projectId: string;
  readonly revisionId: string;
  readonly action: IPipelineAction;
  /** Текущее задание преобразования листа; по нему узнаётся «уже актуально». */
  readonly convertJobId: string | null;
}

export interface IRunPipelineActionResult {
  /** Сервер вернул текущее задание преобразования: CAD не перезапускался. */
  readonly alreadyCurrent: boolean;
}

export const runPipelineAction = async ({
  projectId,
  revisionId,
  action,
  convertJobId,
}: IRunPipelineActionInput): Promise<IRunPipelineActionResult> => {
  const path = {
    project_id: projectId,
    job_id: action.jobId ?? '',
    page_index: action.pageIndex,
    view: action.view ?? 0,
  };
  switch (action.kind) {
    case 'convert': {
      const job = unwrap(
        await createCadJob({
          throwOnError: true,
          path: { project_id: projectId, revision_id: revisionId },
          body: { pages: [action.pageIndex], finishes: false, schedules: false, auto_scale: true },
        }),
      );
      // Тот же ключ идемпотентности: сервер вернул текущее задание, CAD не перезапускался.
      return { alreadyCurrent: convertJobId !== null && job.job_id === convertJobId };
    }
    case 'retry':
      unwrap(
        await retryCadJob({
          throwOnError: true,
          path: { project_id: projectId, revision_id: revisionId, job_id: action.jobId ?? '' },
        }),
      );
      return { alreadyCurrent: false };
    case 'walls':
      unwrap(await recomputeCadWalls({ throwOnError: true, path }));
      return { alreadyCurrent: false };
    case 'zones-auto':
      unwrap(await startCadZonesAuto({ throwOnError: true, path }));
      return { alreadyCurrent: false };
    case 'floor3d':
      unwrap(await createCadFloor3dDxf({ throwOnError: true, path }));
      return { alreadyCurrent: false };
    default:
      return { alreadyCurrent: false };
  }
};
