'use client';

import type { CadBuilding3dFloorRead } from '@quantor/api-client';

import { useCadJob } from '@/lib/cad/queries';
import type { ICadViewParams } from '@/lib/cad/view-queries';
import { workspaceViewParams } from '@/lib/cad/workspace-cad';

export interface IFloorViewParams {
  /** Параметры чтения листа этажа; `null` - этажа нет или результат задания читать нельзя. */
  readonly params: ICadViewParams | null;
  /** Задание ещё читается: параметров пока нет, но они могут появиться. */
  readonly pending: boolean;
}

/**
 * Параметры чтения листа этажа (итоги конструкций, детальный 3D). Попытка-результат (`result_attempt`)
 * есть только у полного задания, поэтому его читают отдельным запросом; в сводке списка её нет.
 */
export const useFloorViewParams = (
  projectId: string,
  floor: CadBuilding3dFloorRead | null,
): IFloorViewParams => {
  const job = useCadJob(projectId, floor?.revision_id ?? null, floor?.job_id ?? null);
  if (floor === null) return { params: null, pending: false };
  if (job.data === undefined) return { params: null, pending: job.isPending && !job.isError };
  return {
    params: workspaceViewParams(projectId, floor.revision_id, job.data, floor.page_index, floor.view),
    pending: false,
  };
};
