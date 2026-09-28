'use client';

import type { CalcPassportRead, CalcScenario } from '@quantor/api-client';
import { useState } from 'react';

import { SynthesisTrace } from '@/components/calc/SynthesisTrace';
import { SystemStructure } from '@/components/calc/SystemStructure';
import { EmptyState, ErrorState, SkeletonRows } from '@/components/ui';
import { useCalcSynthesisTrace } from '@/lib/calc/queries';
import { useVkStructure } from '@/lib/calc/vk-queries';

/**
 * Структура системы паспорта: граф синтеза выбранного сценария. Зоны, стояки, магистрали,
 * подключения — с происхождением; «почему этот элемент нужен» раскрывается до свидетельства.
 */

export const VkStructureTab = ({
  passport,
  scenario,
}: {
  passport: CalcPassportRead;
  scenario: CalcScenario;
}) => {
  const [element, setElement] = useState<string | null>(null);
  const graph = useVkStructure(passport.id, scenario);
  const run = passport.runs.find((item) => item.scenario === scenario);
  const trace = useCalcSynthesisTrace(run?.synthesis_run_id ?? '', element);

  if (!run?.synthesis_run_id) {
    return (
      <EmptyState
        compact
        title="Структура не строилась"
        description="Расчёт системы заблокирован — см. «Неопределённости»."
      />
    );
  }
  if (graph.isError)
    return <ErrorState title="Граф не загрузился" onRetry={() => void graph.refetch()} />;
  if (!graph.data) return <SkeletonRows rows={4} />;
  return (
    <div className="flex flex-col gap-[var(--s-4)]">
      <SystemStructure graph={graph.data} onExplain={setElement} />
      {element !== null &&
        (trace.isError ? (
          <ErrorState title="Объяснение не загрузилось" onRetry={() => void trace.refetch()} />
        ) : trace.data ? (
          <SynthesisTrace trace={trace.data} />
        ) : (
          <SkeletonRows rows={3} />
        ))}
    </div>
  );
};
