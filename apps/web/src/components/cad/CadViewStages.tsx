'use client';

import type { CadAttemptRead, CadProgressViewRead, CadStageRead } from '@quantor/api-client';
import type { FC } from 'react';

import { StatusBadge, cx } from '@/components/ui';
import { viewLabel } from '@/lib/cad/format';
import { CAD_STAGES, formatElapsed, stateLabel, stateTone } from '@/lib/cad/stages';

interface ICadViewStagesProps {
  attempt: CadAttemptRead;
  selectedPage: number | null;
  selectedView: number | null;
  onSelectView: (page: number, view: number) => void;
}

/**
 * Этапы по каждому виду попытки: семь шагов движка. Этап, которого сервер не вернул, показан
 * прочерком, а не «выполнено».
 */
export const CadViewStages: FC<ICadViewStagesProps> = ({
  attempt,
  selectedPage,
  selectedView,
  onSelectView,
}) => (
  <section className="flex flex-col gap-[var(--s-4)]">
    <h3 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">
      Виды и этапы
    </h3>
    {attempt.views.length === 0 ? (
      <p className="text-xs text-muted">Видов пока нет: движок ещё не определил их.</p>
    ) : (
      <ul className="flex flex-col gap-[var(--s-5)]">
        {attempt.views.map((view) => (
          <ViewCard
            key={`${view.page_index}-${view.view}`}
            view={view}
            errorCode={attempt.error_code}
            selected={view.page_index === selectedPage && view.view === selectedView}
            onSelect={() => onSelectView(view.page_index, view.view)}
          />
        ))}
      </ul>
    )}
  </section>
);

interface IViewCardProps {
  view: CadProgressViewRead;
  errorCode: string | null;
  selected: boolean;
  onSelect: () => void;
}

const ViewCard: FC<IViewCardProps> = ({ view, errorCode, selected, onSelect }) => (
  <li
    className={cx(
      'flex flex-col rounded-[var(--radius-md)] border',
      selected ? 'border-accent' : 'border-border',
    )}
  >
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className="flex min-h-[44px] flex-wrap items-center gap-[var(--s-4)] rounded-t-[var(--radius-md)] px-[var(--s-5)] py-[var(--s-3)] text-left hover:bg-surface-muted"
    >
      <span className="text-sm font-medium">{viewLabel(view.page_index, view.view)}</span>
      <span className="mono text-xs text-muted">PDF-страница {view.legacy_pdf_page}</span>
      <StatusBadge tone={stateTone(view.status)}>{stateLabel(view.status)}</StatusBadge>
    </button>
    <ul className="grid grid-cols-1 gap-px border-t border-border bg-border min-[480px]:grid-cols-2 xl:grid-cols-4 min-[1400px]:grid-cols-7">
      {CAD_STAGES.map((definition) => (
        <StageCell
          key={definition.key}
          label={definition.label}
          stage={view.stages.find((item) => item.key === definition.key) ?? null}
          errorCode={errorCode}
        />
      ))}
    </ul>
  </li>
);

interface IStageCellProps {
  label: string;
  stage: CadStageRead | null;
  errorCode: string | null;
}

const StageCell: FC<IStageCellProps> = ({ label, stage, errorCode }) => {
  const failed = stage?.status === 'error';

  return (
    <li
      className={cx(
        'flex min-w-0 flex-col gap-[var(--s-2)] bg-surface px-[var(--s-4)] py-[var(--s-3)] text-xs',
        failed && 'bg-danger-soft',
      )}
    >
      <span className="text-muted">{label}</span>
      {stage === null ? (
        <span className="text-muted" aria-label="Этап не сообщён">
          —
        </span>
      ) : (
        <>
          <span>
            <StatusBadge tone={stateTone(stage.status)} dot={false}>
              {stateLabel(stage.status)}
            </StatusBadge>
          </span>
          <span className="mono text-muted">
            {formatElapsed(stage.elapsed_s)}
            {stage.total !== null && ` · ${stage.completed ?? 0}/${stage.total}`}
            {stage.total === null && stage.completed !== null && ` · ${stage.completed}`}
          </span>
          {stage.detail && <span className="[overflow-wrap:anywhere]">{stage.detail}</span>}
          {failed && errorCode && <span className="mono text-danger">{errorCode}</span>}
        </>
      )}
    </li>
  );
};
