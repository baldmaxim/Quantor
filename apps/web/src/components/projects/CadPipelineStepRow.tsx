import type { FC } from 'react';

import { Button, ButtonLink, buttonClassName, StatusBadge } from '@/components/ui';
import { isMachineAction, type IPipelineAction, type IPipelineRow } from '@/lib/cad/pipeline-actions';
import { PIPELINE_STATE_TONES, PIPELINE_STATE_WORDS } from '@/lib/cad/pipeline-view';

import { CadPipelineStageError } from './CadPipelineStageError';

/**
 * Строка шага в панели управления листом: состояние, ход или причина отказа и действия справа
 * (на узком экране переносятся под строку). Компонент только рисует описания действий.
 */

export interface ICadPipelineStepRowProps {
  readonly projectId: string;
  readonly revisionId: string;
  readonly row: IPipelineRow;
  /** Идущее действие листа; пока оно есть, остальные кнопки заблокированы. */
  readonly pendingId: string | null;
  readonly error: string | null;
  /** Пояснение без ошибки: действие ничего не изменило. */
  readonly notice?: string | null;
  readonly onAction: (action: IPipelineAction) => void;
}

const TAP = 'max-md:h-[44px]';

export const CadPipelineStepRow: FC<ICadPipelineStepRowProps> = ({
  projectId,
  revisionId,
  row,
  pendingId,
  error,
  notice = null,
  onAction,
}) => {
  const { step, stage } = row;
  const failed = step.state === 'failed';
  // Порог качества: результат готов, но требует проверки - причины списком под шагом.
  const review = step.review ?? [];

  return (
    <li className="flex flex-col gap-[var(--s-2)] border-b border-border py-[var(--s-3)] last:border-b-0">
      <div className="flex flex-wrap items-start justify-between gap-x-[var(--s-4)] gap-y-[var(--s-3)]">
        <div className="flex min-w-0 flex-1 flex-col gap-[var(--s-1)]">
          <div className="flex flex-wrap items-center gap-x-[var(--s-3)] gap-y-[var(--s-2)]">
            <StatusBadge tone={review.length > 0 ? 'warning' : PIPELINE_STATE_TONES[step.state]} wrap>
              {review.length > 0 ? 'на проверку' : PIPELINE_STATE_WORDS[step.state]}
            </StatusBadge>
            <span className="text-sm font-medium">{step.label}</span>
            {row.viewLabel && <span className="text-xs text-muted">{row.viewLabel}</span>}
          </div>
          {!failed && step.detail && (
            <p className="m-0 text-xs text-muted [overflow-wrap:anywhere]">{step.detail}</p>
          )}
          {review.length > 0 && (
            <ul className="m-0 list-disc pl-[var(--s-5)] text-xs text-warning [overflow-wrap:anywhere]">
              {review.map((reason) => (
                <li key={reason}>{reason}</li>
              ))}
            </ul>
          )}
        </div>
        {row.actions.length > 0 && (
          <div className="flex flex-wrap items-center gap-[var(--s-3)]">
            {row.actions.map((action) => {
              if (action.kind === 'link' && action.href) {
                return (
                  <ButtonLink key={action.id} href={action.href} compact className={TAP}>
                    {action.label}
                  </ButtonLink>
                );
              }
              if (action.kind === 'download' && action.href) {
                return (
                  <a
                    key={action.id}
                    href={action.href}
                    download
                    className={buttonClassName({ compact: true, className: TAP })}
                  >
                    {action.label}
                  </a>
                );
              }
              if (!isMachineAction(action)) return null;
              const pending = pendingId === action.id;
              return (
                <Button
                  key={action.id}
                  compact
                  variant={action.intent === 'redo' ? 'default' : 'primary'}
                  loading={pending}
                  loadingLabel="Запуск…"
                  disabled={pendingId !== null}
                  onClick={() => onAction(action)}
                  className={TAP}
                >
                  {action.label}
                </Button>
              );
            })}
          </div>
        )}
      </div>
      {failed && stage && (
        <CadPipelineStageError
          projectId={projectId}
          revisionId={revisionId}
          stage={stage}
          text={step.detail}
        />
      )}
      {error && (
        <p role="alert" className="m-0 text-xs text-danger [overflow-wrap:anywhere]">
          {error}
        </p>
      )}
      {notice && !error && (
        <p role="status" className="m-0 text-xs text-muted [overflow-wrap:anywhere]">
          {notice}
        </p>
      )}
    </li>
  );
};
