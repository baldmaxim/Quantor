'use client';

import {
  createCadFloor3dDxf,
  recomputeCadWalls,
  retryCadJob,
  startCadZonesAuto,
} from '@quantor/api-client';
import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useCallback, useRef, useState } from 'react';

import { cadErrorText } from '@/lib/cad/errors';
import type { IPipelineAction } from '@/lib/cad/pipeline-actions';
import { cadPipelineKey } from '@/lib/cad/pipeline-queries';
import { cadKeys, useCreateCadJob, useRetryCadJob } from '@/lib/cad/queries';
import { unwrap } from '@/lib/queries';

/**
 * Запуск действий листа из панели «Обработка»: одна мутация на лист, одно действие за раз.
 * Преобразование и его повтор идут через общие хуки CAD, остальное - через клиент из OpenAPI.
 * После любого исхода конвейер ревизии перечитывается: его опрос подхватит идущее задание.
 */

export interface ISheetPipelineActions {
  readonly run: (action: IPipelineAction) => void;
  /** Идущее действие; `null` - ничего не запускается. */
  readonly pendingId: string | null;
  /** Тексты отказов по идентификатору действия. */
  readonly errors: Readonly<Record<string, string>>;
}

export const useSheetPipelineActions = (
  projectId: string,
  revisionId: string,
  convertJobId: string | null,
): ISheetPipelineActions => {
  const client = useQueryClient();
  const create = useCreateCadJob(projectId, revisionId);
  const retry = useRetryCadJob(projectId, revisionId, convertJobId ?? '');
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});
  // Синхронная защита от двойного нажатия: isPending обновляется после рендера.
  const launching = useRef(false);

  const mutation = useMutation<void, unknown, IPipelineAction>({
    mutationFn: async (action) => {
      const path = {
        project_id: projectId,
        job_id: action.jobId ?? '',
        page_index: action.pageIndex,
        view: action.view ?? 0,
      };
      switch (action.kind) {
        case 'convert':
          await create.mutateAsync({ pages: [action.pageIndex] });
          return;
        case 'retry':
          if (action.jobId === convertJobId) {
            await retry.mutateAsync();
          } else {
            const retryPath = {
              project_id: projectId,
              revision_id: revisionId,
              job_id: action.jobId ?? '',
            };
            unwrap(await retryCadJob({ throwOnError: true, path: retryPath }));
          }
          return;
        case 'walls':
          unwrap(await recomputeCadWalls({ throwOnError: true, path }));
          return;
        case 'zones-auto':
          unwrap(await startCadZonesAuto({ throwOnError: true, path }));
          return;
        case 'floor3d':
          unwrap(await createCadFloor3dDxf({ throwOnError: true, path }));
          return;
        default:
          return;
      }
    },
    onSettled: () => {
      launching.current = false;
      void client.invalidateQueries({ queryKey: cadPipelineKey(projectId, revisionId) });
      void client.invalidateQueries({ queryKey: cadKeys.jobs(projectId, revisionId) });
      void client.invalidateQueries({ queryKey: ['cad-constructions', projectId, revisionId] });
    },
  });

  const run = useCallback(
    (action: IPipelineAction) => {
      if (launching.current) return;
      launching.current = true;
      setErrors((previous) =>
        Object.fromEntries(Object.entries(previous).filter(([id]) => id !== action.id)),
      );
      mutation.mutate(action, {
        onError: (error) =>
          setErrors((previous) => ({ ...previous, [action.id]: cadErrorText(error) })),
      });
    },
    [mutation],
  );

  return {
    run,
    pendingId: mutation.isPending ? (mutation.variables?.id ?? null) : null,
    errors,
  };
};
