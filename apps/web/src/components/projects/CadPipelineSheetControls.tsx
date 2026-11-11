'use client';

import type { CadPipelineSheetRead } from '@quantor/api-client';
import { useMemo, useState, type FC } from 'react';

import { Button, ButtonLink, Dialog, DialogActions } from '@/components/ui';
import {
  isMachineAction,
  nextPipelineAction,
  sheetRows,
  type IPipelineAction,
} from '@/lib/cad/pipeline-actions';

import { CadPipelineStepRow } from './CadPipelineStepRow';
import { useSheetPipelineActions } from './useSheetPipelineActions';

/**
 * Панель управления листом: шаги конвейера с состоянием, причиной отказа и действиями, сверху -
 * главная кнопка следующего шага. Решения человека (калибровка, одобрение, принятие трасс)
 * не автоматизируются: для них - переход в рабочую область.
 */

export interface ICadPipelineSheetControlsProps {
  readonly projectId: string;
  readonly revisionId: string;
  readonly sheet: CadPipelineSheetRead;
  /** Позиция листа в рабочей области (с 1). */
  readonly position: number;
}

export const CadPipelineSheetControls: FC<ICadPipelineSheetControlsProps> = ({
  projectId,
  revisionId,
  sheet,
  position,
}) => {
  const rows = useMemo(
    () => sheetRows(projectId, revisionId, position, sheet),
    [projectId, revisionId, position, sheet],
  );
  const next = useMemo(() => nextPipelineAction(rows), [rows]);
  const actions = useSheetPipelineActions(projectId, revisionId, sheet.convert?.job_id ?? null);
  const [confirming, setConfirming] = useState<IPipelineAction | null>(null);

  const request = (action: IPipelineAction) => {
    if (action.confirm) setConfirming(action);
    else actions.run(action);
  };

  const confirm = () => {
    if (confirming) actions.run(confirming);
    setConfirming(null);
  };

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-3)]">
      {next && next.action.kind === 'link' && next.action.href && (
        <ButtonLink
          href={next.action.href}
          variant="primary"
          compact
          className="self-start max-md:h-[44px] max-md:w-full"
        >
          {`Перейти: ${next.row.step.label}`}
        </ButtonLink>
      )}
      {next && isMachineAction(next.action) && (
        <Button
          variant="primary"
          compact
          loading={actions.pendingId === next.action.id}
          loadingLabel="Запуск…"
          disabled={actions.pendingId !== null}
          onClick={() => request(next.action)}
          className="self-start max-md:h-[44px] max-md:w-full"
        >
          {`Следующий шаг: ${next.row.step.label}`}
        </Button>
      )}
      <ul className="m-0 list-none p-0" aria-label="Шаги листа">
        {rows.map((row) => (
          <CadPipelineStepRow
            key={row.id}
            projectId={projectId}
            revisionId={revisionId}
            row={row}
            pendingId={actions.pendingId}
            error={row.actions.map((action) => actions.errors[action.id]).find(Boolean) ?? null}
            onAction={request}
          />
        ))}
      </ul>
      <Dialog
        open={confirming !== null}
        onClose={() => setConfirming(null)}
        title="Преобразовать лист заново?"
        footer={
          <DialogActions>
            <Button onClick={() => setConfirming(null)}>Отмена</Button>
            <Button variant="primary" onClick={confirm}>
              Преобразовать заново
            </Button>
          </DialogActions>
        }
      >
        <p className="text-sm">
          Лист будет преобразован текущей версией CAD-движка. Конструкции пересчитаются автоматически,
          зоны листа сохранятся. Одобрение вида и трассы нужно будет сделать заново; ручные параметры
          части конструкций могут сброситься.
        </p>
      </Dialog>
    </div>
  );
};
