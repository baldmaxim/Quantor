'use client';

import type { CalcRunRead } from '@quantor/api-client';
import { useState } from 'react';

import { RunTrace } from '@/components/calc/RunTrace';
import { RunsTable } from '@/components/calc/RunsTable';
import { Button, EmptyState, ErrorState, SkeletonRows, StatusBadge } from '@/components/ui';
import { unitTitle } from '@/lib/calc/format';
import { useCalcRun, useCalcRunTrace, useCalcRuns } from '@/lib/calc/queries';
import { RUN_STATUS, SCENARIO_TITLES, formatExact } from '@/lib/calc/runs';

/**
 * Экран «Расчёты → Запуски»: диагностический, только чтение. Запуск идёт через API ядра;
 * здесь — итог, причины блокировки и «Почему такое значение?».
 */

export const CalcRuns = ({ projectId }: { projectId: string }) => {
  const [selected, setSelected] = useState<string | null>(null);
  const runs = useCalcRuns(projectId, true);
  const run = useCalcRun(selected);

  if (runs.isError) {
    return <ErrorState title="Запуски не загрузились" onRetry={() => void runs.refetch()} />;
  }
  if (!runs.data) return <SkeletonRows rows={4} />;
  if (runs.data.length === 0) {
    return (
      <EmptyState
        compact
        title="Запусков пока нет"
        description="Расчёт запускается через API ядра. Реальных калькуляторов систем ещё нет — только демонстрационный."
      />
    );
  }

  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      <RunsTable runs={runs.data} selected={selected} onSelect={setSelected} />
      {selected !== null &&
        (run.isError ? (
          <ErrorState title="Запуск не загрузился" onRetry={() => void run.refetch()} />
        ) : run.data ? (
          <RunDetails key={run.data.id} run={run.data} />
        ) : (
          <SkeletonRows rows={3} />
        ))}
    </div>
  );
};

const RunDetails = ({ run }: { run: CalcRunRead }) => {
  const [resultKey, setResultKey] = useState<string | null>(null);
  const trace = useCalcRunTrace(run.id, resultKey);
  const status = RUN_STATUS[run.status];

  return (
    <section className="flex flex-col gap-[var(--s-4)] rounded-[var(--radius-md)] border border-border-strong bg-surface px-[var(--s-5)] py-[var(--s-5)]">
      <header className="flex flex-wrap items-center gap-[var(--s-3)]">
        <h2 className="text-base font-medium">{run.calculator_title}</h2>
        <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
        <span className="text-sm text-muted">{SCENARIO_TITLES[run.scenario]}</span>
      </header>

      {run.blocking_reasons.length > 0 && (
        <ul className="flex list-disc flex-col gap-[var(--s-1)] pl-[var(--s-5)] text-sm">
          {run.blocking_reasons.map((reason, index) => (
            <li key={index} className="wrap-anywhere">
              <span className="font-mono text-xs text-muted">{reason.code}</span> {reason.message}
            </li>
          ))}
        </ul>
      )}
      {run.failure && <p className="text-sm text-danger wrap-anywhere">{run.failure.message}</p>}
      {run.warnings.map((warning) => (
        <p key={warning} className="text-sm text-warning wrap-anywhere">
          {warning}
        </p>
      ))}

      {run.results.length > 0 && (
        <ul className="flex list-none flex-col gap-[var(--s-2)]">
          {run.results.map((result) => (
            <li
              key={result.result_key}
              className="flex flex-wrap items-center gap-x-[var(--s-4)] gap-y-[var(--s-2)] text-sm"
            >
              <span className="min-w-0 flex-1 wrap-anywhere">{result.title}</span>
              <span className="tabular font-medium">
                {formatExact(result.value)} {unitTitle(result.unit)}
              </span>
              <Button compact onClick={() => setResultKey(result.result_key)}>
                Почему такое значение?
              </Button>
            </li>
          ))}
        </ul>
      )}

      {resultKey !== null &&
        (trace.isError ? (
          <ErrorState title="Объяснение не загрузилось" onRetry={() => void trace.refetch()} />
        ) : trace.data ? (
          <RunTrace trace={trace.data} />
        ) : (
          <SkeletonRows rows={3} />
        ))}
    </section>
  );
};
