'use client';

import { useState } from 'react';

import { MepExperiment } from '@/components/mep/MepExperiment';
import { TopBar } from '@/components/shell/TopBar';
import {
  EmptyState,
  ErrorState,
  SegmentedControl,
  SkeletonRows,
  StatusBadge,
} from '@/components/ui';
import { mepAccess } from '@/lib/mep/access';
import { useMepScenario, useMepScenarios } from '@/lib/mep/queries';
import { useFeatures, useMeta } from '@/lib/queries';

/**
 * MEP-эксперимент П → РД → ВОР в режиме MOCK (ADR-0027, PROMPT 11).
 *
 * Только синтетические сценарии. Evidence, сеть и ВОР приходят с сервера: граф проверяют
 * контракты, количества считает Quantity Engine. При выключенном флаге страницы нет.
 */
const MepExperimentPage = () => {
  const meta = useMeta();
  const access = mepAccess(meta.isSuccess, useFeatures());
  const scenarios = useMepScenarios(access === 'open');
  const [scenarioId, setScenarioId] = useState<string>('complete');
  const scenario = useMepScenario(access === 'open' ? scenarioId : null);

  // Пока решения нет — нейтральная заглушка без названия эксперимента.
  if (access === 'pending') {
    return (
      <main className="min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)]">
        <SkeletonRows rows={6} />
      </main>
    );
  }

  // Флаг выключен: ни данных, ни упоминания эксперимента — как у несуществующего адреса.
  if (access === 'hidden') {
    return (
      <main className="min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)]">
        <EmptyState title="Страница не найдена" />
      </main>
    );
  }

  return (
    <>
      <TopBar
        crumbs={[{ label: 'Эксперименты' }, { label: 'MEP · П → РД → ВОР' }]}
        status={<StatusBadge tone="warning">MOCK · синтетика</StatusBadge>}
      />
      <main className="min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)]">
        <div className="mx-auto flex w-full max-w-[1440px] flex-col gap-[var(--s-5)]">
          <p className="text-sm text-muted">
            Проверочная цепочка на синтетических данных: что показано на П, что построил генератор
            РД и какие физические количества из этого следуют. Модель, распознавание и цены не
            подключены.
          </p>

          <SegmentedControl
            label="Сценарии"
            layout="wrap"
            value={scenarioId ?? ''}
            onChange={setScenarioId}
            options={(scenarios.data ?? []).map((item) => ({
              value: item.scenario_id,
              label: item.title,
              hint: item.description,
            }))}
          />

          {scenario.isError ? (
            <ErrorState title="Сценарий не загрузился" onRetry={() => void scenario.refetch()} />
          ) : scenario.data ? (
            <>
              <p className="text-sm">{scenario.data.scenario.description}</p>
              <MepExperiment key={scenario.data.scenario.scenario_id} scenario={scenario.data} />
            </>
          ) : (
            <SkeletonRows rows={6} />
          )}
        </div>
      </main>
    </>
  );
};

export default MepExperimentPage;
