import type { CadPipelineSheetRead } from '@quantor/api-client';

import {
  isBulkLaunchable,
  isMachineAction,
  nextPipelineAction,
  type IPipelineAction,
  type IPipelineRow,
} from './pipeline-actions';

/**
 * Выбор следующего шага листа для массового запуска конвейера (без React): запускаются только
 * машинные шаги, которые не отработаны; решения человека (калибровка, одобрение, трассы) -
 * конец работы над листом.
 */

export type BatchOutcome = 'ready' | 'human';

export type BatchDecision =
  /** На листе что-то идёт или стоит в очереди: ждём обновления конвейера. */
  | { readonly kind: 'wait' }
  | { readonly kind: 'run'; readonly action: IPipelineAction; readonly key: string }
  /** Лист завершён: `ready` - машинных шагов не осталось, `human` - дальше решает человек. */
  | { readonly kind: 'done'; readonly outcome: BatchOutcome }
  /** Это же действие уже запускалось в партии и шаг снова не прошёл. */
  | { readonly kind: 'failed'; readonly message: string };

export const batchStepFailedAgain = (label: string): string => `Шаг «${label}» снова не выполнился`;

/** Ключ запуска в партии: действие и задание, над которым оно работало. */
export const batchActionKey = (action: IPipelineAction): string =>
  `${action.id}:${action.jobId ?? ''}`;

/**
 * Идущий шаг листа. Необязательные 3D DXF и калибровка в ожидание не входят: калибровка -
 * решение человека, 3D DXF в конвейер не включён.
 */
const hasActiveStep = (rows: readonly IPipelineRow[]): boolean =>
  rows.some(
    (row) =>
      row.key !== 'floor3d' &&
      row.key !== 'calibration' &&
      (row.step.state === 'running' || row.step.state === 'queued'),
  );

/** Следующее машинное действие листа или `null`, если дальше ждёт человек или всё готово. */
export const machineNextAction = (rows: readonly IPipelineRow[]): IPipelineAction | null => {
  const next = nextPipelineAction(rows);
  return next && isMachineAction(next.action) ? next.action : null;
};

/** Лист можно выбрать для запуска конвейера: преобразование доступно или есть машинный шаг. */
export const isPipelineSelectable = (
  sheet: CadPipelineSheetRead,
  rows: readonly IPipelineRow[],
): boolean => isBulkLaunchable(sheet) || machineNextAction(rows) !== null;

export const nextBatchStep = (
  rows: readonly IPipelineRow[],
  launched: ReadonlySet<string>,
): BatchDecision => {
  if (hasActiveStep(rows)) return { kind: 'wait' };
  const next = nextPipelineAction(rows);
  if (next === null) return { kind: 'done', outcome: 'ready' };
  if (!isMachineAction(next.action)) return { kind: 'done', outcome: 'human' };
  const key = batchActionKey(next.action);
  if (launched.has(key))
    return { kind: 'failed', message: batchStepFailedAgain(next.row.step.label) };
  return { kind: 'run', action: next.action, key };
};
