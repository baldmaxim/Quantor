'use client';

import type { CalcRunSummaryRead } from '@quantor/api-client';

import { Button, StatusBadge, cx } from '@/components/ui';
import { RUN_STATUS, SCENARIO_TITLES } from '@/lib/calc/runs';
import { formatWhen } from '@/lib/format';

/**
 * Запуски расчёта проекта: калькулятор, сценарий, итог, дата, число результатов, причина
 * блокировки. На телефоне строка разворачивается в карточку.
 */

const COLUMNS = 'minmax(200px,1.6fr) 130px 130px 150px 90px minmax(200px,1.4fr) 110px';

interface IRunsTableProps {
  runs: readonly CalcRunSummaryRead[];
  selected: string | null;
  onSelect: (runId: string) => void;
}

export const RunsTable = ({ runs, selected, onSelect }: IRunsTableProps) => (
  <div className="overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface">
    <div
      role="row"
      className="hidden items-center gap-[var(--s-5)] border-b border-border bg-surface-muted px-[var(--s-6)] py-[var(--s-4)] text-micro tracking-[0.06em] text-muted uppercase lg:grid"
      style={{ gridTemplateColumns: COLUMNS }}
    >
      <span>Калькулятор</span>
      <span>Сценарий</span>
      <span>Статус</span>
      <span>Дата</span>
      <span>Результатов</span>
      <span>Причина</span>
      <span />
    </div>
    <ul className="list-none">
      {runs.map((run) => {
        const status = RUN_STATUS[run.status];
        return (
          <li
            key={run.id}
            className={cx(
              'flex flex-wrap items-start gap-x-[var(--s-5)] gap-y-[var(--s-2)] border-b border-border px-[var(--s-5)] py-[var(--s-4)] text-sm last:border-b-0',
              'lg:grid lg:gap-x-[var(--s-5)] lg:px-[var(--s-6)] lg:py-[var(--s-3)]',
              run.id === selected && 'bg-accent-soft',
            )}
            style={{ gridTemplateColumns: COLUMNS }}
          >
            <span className="flex min-w-0 basis-full flex-col lg:basis-auto">
              <span className="font-medium wrap-anywhere">{run.calculator_title}</span>
              <span className="font-mono text-xs text-muted">
                {run.calculator_id}@{run.calculator_version}
              </span>
            </span>
            <span>{SCENARIO_TITLES[run.scenario]}</span>
            <span>
              <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
            </span>
            <span className="text-xs text-muted">{formatWhen(run.created_at)}</span>
            <span className="tabular">{run.results_count}</span>
            <span className="basis-full text-xs text-muted wrap-anywhere lg:basis-auto">
              {run.blocking ?? '—'}
            </span>
            <span>
              <Button compact onClick={() => onSelect(run.id)}>
                Открыть
              </Button>
            </span>
          </li>
        );
      })}
    </ul>
  </div>
);
