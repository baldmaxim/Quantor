'use client';

import type { CalcSynthesisRunRead, CalcSystemGraph } from '@quantor/api-client';
import { useState } from 'react';

import { SynthesisTrace } from '@/components/calc/SynthesisTrace';
import { SystemStructure } from '@/components/calc/SystemStructure';
import { Button, EmptyState, ErrorState, SkeletonRows, StatusBadge, cx } from '@/components/ui';
import {
  useCalcSynthesisRun,
  useCalcSynthesisRuns,
  useCalcSynthesisTrace,
} from '@/lib/calc/queries';
import { SCENARIO_TITLES } from '@/lib/calc/runs';
import { SYNTHESIS_STATUS } from '@/lib/calc/synthesis';
import { formatWhen } from '@/lib/format';

/**
 * Экран «Расчёты → Структура системы»: диагностический, только чтение. Синтез запускается через
 * API; здесь — логическая структура, варианты, что неизвестно и «почему этот элемент нужен».
 */

export const CalcStructure = ({ projectId }: { projectId: string }) => {
  const [selected, setSelected] = useState<string | null>(null);
  const runs = useCalcSynthesisRuns(projectId);
  const run = useCalcSynthesisRun(selected);

  if (runs.isError) {
    return (
      <ErrorState title="Запуски синтеза не загрузились" onRetry={() => void runs.refetch()} />
    );
  }
  if (!runs.data) return <SkeletonRows rows={4} />;
  if (runs.data.length === 0) {
    return (
      <EmptyState
        compact
        title="Структура ещё не строилась"
        description="Синтез запускается через API по успешному запуску расчёта. Реальных синтезаторов систем ещё нет."
      />
    );
  }

  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      <ul className="flex list-none flex-col overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface">
        {runs.data.map((item) => {
          const status = SYNTHESIS_STATUS[item.status];
          return (
            <li
              key={item.id}
              className={cx(
                'flex flex-wrap items-center gap-x-[var(--s-4)] gap-y-[var(--s-2)] border-b border-border px-[var(--s-5)] py-[var(--s-3)] text-sm last:border-b-0',
                item.id === selected && 'bg-accent-soft',
              )}
            >
              <span className="min-w-0 flex-1 font-medium wrap-anywhere">
                {item.synthesizer_title}
              </span>
              <span>{SCENARIO_TITLES[item.scenario]}</span>
              <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
              <span className="text-xs text-muted">{formatWhen(item.created_at)}</span>
              <span className="text-xs text-muted">
                элементов {item.nodes_count} · открыто {item.unresolved_count}
              </span>
              {item.blocking && (
                <span className="basis-full text-xs text-muted wrap-anywhere">{item.blocking}</span>
              )}
              <Button compact onClick={() => setSelected(item.id)}>
                Открыть
              </Button>
            </li>
          );
        })}
      </ul>
      {selected !== null &&
        (run.isError ? (
          <ErrorState title="Запуск не загрузился" onRetry={() => void run.refetch()} />
        ) : run.data ? (
          <RunDetails key={run.data.run.id} run={run.data.run} graph={run.data.graph} />
        ) : (
          <SkeletonRows rows={3} />
        ))}
    </div>
  );
};

const RunDetails = ({
  run,
  graph,
}: {
  run: CalcSynthesisRunRead;
  graph: CalcSystemGraph | null;
}) => {
  const [element, setElement] = useState<string | null>(null);
  const trace = useCalcSynthesisTrace(run.id, element);

  return (
    <section className="flex flex-col gap-[var(--s-4)] rounded-[var(--radius-md)] border border-border-strong bg-surface px-[var(--s-5)] py-[var(--s-5)]">
      <header className="flex flex-wrap items-center gap-[var(--s-3)]">
        <h2 className="text-base font-medium">{run.synthesizer_title}</h2>
        <StatusBadge tone={SYNTHESIS_STATUS[run.status].tone}>
          {SYNTHESIS_STATUS[run.status].label}
        </StatusBadge>
      </header>
      {run.blocking_reasons.map((reason, index) => (
        <p key={index} className="text-sm wrap-anywhere">
          <span className="font-mono text-xs text-muted">{reason.code}</span> {reason.message}
        </p>
      ))}
      {run.warnings.map((warning) => (
        <p key={warning} className="text-sm text-warning wrap-anywhere">
          {warning}
        </p>
      ))}
      {graph && <SystemStructure graph={graph} onExplain={setElement} />}
      {run.variants.length > 0 && (
        <section className="flex flex-col gap-[var(--s-2)]">
          <h3 className="text-sm font-medium">Допустимые варианты — без вероятностей</h3>
          <ul className="flex list-disc flex-col gap-[var(--s-1)] pl-[var(--s-5)] text-sm">
            {run.variants.map((variant) => (
              <li key={variant.key} className="wrap-anywhere">
                {variant.title}: {variant.reasons.join('; ')}
              </li>
            ))}
          </ul>
        </section>
      )}
      {element !== null &&
        (trace.isError ? (
          <ErrorState title="Объяснение не загрузилось" onRetry={() => void trace.refetch()} />
        ) : trace.data ? (
          <SynthesisTrace trace={trace.data} />
        ) : (
          <SkeletonRows rows={3} />
        ))}
    </section>
  );
};
