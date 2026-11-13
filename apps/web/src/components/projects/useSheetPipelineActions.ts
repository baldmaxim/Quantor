'use client';

import { useMutation, useQueryClient } from '@tanstack/react-query';
import { useCallback, useRef, useState } from 'react';

import { cadErrorText } from '@/lib/cad/errors';
import type { IPipelineAction } from '@/lib/cad/pipeline-actions';
import { cadPipelineKey } from '@/lib/cad/pipeline-queries';
import { cadSummaryKey } from '@/lib/cad/queue-queries';
import { cadKeys } from '@/lib/cad/queries';
import { runPipelineAction } from '@/lib/cad/runPipelineAction';

/**
 * Запуск действий листа из панели «Обработка»: одна мутация на лист, одно действие за раз.
 * Исполнение - общая функция `runPipelineAction` (её же использует массовый запуск конвейера).
 * После любого исхода конвейер ревизии перечитывается: его опрос подхватит идущее задание.
 */

export const ALREADY_CURRENT =
  'Уже актуально: лист преобразован текущей версией движка с этой калибровкой — CAD не перезапускался. ' +
  'Изменения стен, плиты и зон применяются пересчётом шага «Конструкции» или «Зоны».';

export interface ISheetPipelineActions {
  readonly run: (action: IPipelineAction) => void;
  /** Идущее действие; `null` - ничего не запускается. */
  readonly pendingId: string | null;
  /** Тексты отказов по идентификатору действия. */
  readonly errors: Readonly<Record<string, string>>;
  /** Пояснения без ошибки по идентификатору действия: «уже актуально». */
  readonly notices: Readonly<Record<string, string>>;
}

export const useSheetPipelineActions = (
  projectId: string,
  revisionId: string,
  convertJobId: string | null,
): ISheetPipelineActions => {
  const client = useQueryClient();
  const [errors, setErrors] = useState<Readonly<Record<string, string>>>({});
  const [notices, setNotices] = useState<Readonly<Record<string, string>>>({});
  // Синхронная защита от двойного нажатия: isPending обновляется после рендера.
  const launching = useRef(false);

  const mutation = useMutation<void, unknown, IPipelineAction>({
    mutationFn: async (action) => {
      const result = await runPipelineAction({ projectId, revisionId, action, convertJobId });
      if (result.alreadyCurrent) {
        setNotices((previous) => ({ ...previous, [action.id]: ALREADY_CURRENT }));
      }
    },
    onSettled: (_data, _error, action) => {
      launching.current = false;
      void client.invalidateQueries({ queryKey: cadPipelineKey(projectId, revisionId) });
      void client.invalidateQueries({ queryKey: cadKeys.jobs(projectId, revisionId) });
      void client.invalidateQueries({ queryKey: cadSummaryKey(projectId) });
      if (action.kind === 'retry' && action.jobId !== null) {
        void client.invalidateQueries({
          queryKey: cadKeys.job(projectId, revisionId, action.jobId),
        });
      }
      void client.invalidateQueries({ queryKey: ['cad-constructions', projectId, revisionId] });
    },
  });

  const run = useCallback(
    (action: IPipelineAction) => {
      if (launching.current) return;
      launching.current = true;
      const without = (previous: Readonly<Record<string, string>>) =>
        Object.fromEntries(Object.entries(previous).filter(([id]) => id !== action.id));
      setErrors(without);
      setNotices(without);
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
    notices,
  };
};
