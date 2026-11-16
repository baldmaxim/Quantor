import type { CadPipelineSheetRead, CadPipelineStaleRead } from '@quantor/api-client';

import { isUpdateActive } from './pipeline';
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
): boolean =>
  !isUpdateActive(sheet) && (isBulkLaunchable(sheet) || machineNextAction(rows) !== null);

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

/**
 * Действие, пересчитывающее устаревший этап листа. Преобразование - новый прогон движка (за ним
 * конструкции пересчитаются сами); конструкции - пересчёт вида; зоны - повторная авторазметка, и
 * только у листа с одним видом: зоны хранятся по листу, и разметка одного вида заменила бы зоны
 * остальных. Трассы в пересчёт не входят.
 */
const staleAction = (
  item: CadPipelineStaleRead,
  rows: readonly IPipelineRow[],
): IPipelineAction | null => {
  if (item.stage === 'convert') {
    const row = rows.find((candidate) => candidate.key === 'convert');
    return row?.actions.find((candidate) => candidate.kind === 'convert') ?? null;
  }
  if (item.stage === 'walls') {
    const row = rows.find((candidate) => candidate.key === 'walls' && candidate.view === item.view);
    return row?.actions.find((candidate) => candidate.kind === 'walls') ?? null;
  }
  const zones = rows.filter((candidate) => candidate.key === 'zones' && candidate.view !== null);
  if (zones.length !== 1) return null;
  return zones[0]?.actions.find((candidate) => candidate.kind === 'zones-auto') ?? null;
};

/** Первое доступное действие пересчёта устаревшего листа; пересчитывать нечего - `null`. */
export const staleNextAction = (
  sheet: CadPipelineSheetRead,
  rows: readonly IPipelineRow[],
): IPipelineAction | null => {
  for (const item of sheet.stale ?? []) {
    const found = staleAction(item, rows);
    if (found) return found;
  }
  return null;
};

/** Лист можно выбрать для пересчёта устаревших: есть устаревший этап с доступным пересчётом. */
export const isStaleRecomputable = (
  sheet: CadPipelineSheetRead,
  rows: readonly IPipelineRow[],
): boolean => !isUpdateActive(sheet) && staleNextAction(sheet, rows) !== null;

/**
 * Следующий шаг листа в партии «Пересчитать устаревшие»: по одному устаревшему этапу за раз, в
 * порядке конвейера. Лист без устаревших этапов закончен; решения человека не запускаются.
 */
export const nextStaleStep = (
  sheet: CadPipelineSheetRead,
  rows: readonly IPipelineRow[],
  launched: ReadonlySet<string>,
): BatchDecision => {
  if (hasActiveStep(rows)) return { kind: 'wait' };
  const next = staleNextAction(sheet, rows);
  if (next === null) return { kind: 'done', outcome: 'ready' };
  const key = batchActionKey(next);
  if (launched.has(key)) {
    const row = rows.find((candidate) => candidate.actions.includes(next));
    return { kind: 'failed', message: batchStepFailedAgain(row?.step.label ?? next.label) };
  }
  return { kind: 'run', action: next, key };
};
