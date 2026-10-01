'use client';

import { use } from 'react';

import { CalcRules } from '@/components/calc/CalcRules';
import { TopBar } from '@/components/shell/TopBar';
import { EmptyState, SkeletonRows, StatusBadge } from '@/components/ui';
import { calcAccess } from '@/lib/calc/access';
import { useFeatures, useMeta, useProject } from '@/lib/queries';

/**
 * Расчёты → Правила (ADR-0030, PROMPT 03).
 *
 * Закрыто флагом `calc.portal`. Реестр правил — общий для пространства; вход — из расчётов
 * проекта, чтобы путь «Расчёты → Правила» был один.
 */

interface IPageProps {
  params: Promise<{ projectId: string }>;
}

const CalcRulesPage = ({ params }: IPageProps) => {
  const { projectId } = use(params);
  const meta = useMeta();
  const access = calcAccess(meta.isSuccess, useFeatures());
  const project = useProject(projectId);

  if (access === 'pending') {
    return (
      <main className="min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)]">
        <SkeletonRows rows={6} />
      </main>
    );
  }

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
        crumbs={[
          { label: 'Проекты', href: '/projects' },
          { label: project.data?.name ?? '…', href: `/projects/${projectId}` },
          { label: 'Расчёты', href: `/projects/${projectId}/calc` },
          { label: 'Правила' },
        ]}
        status={<StatusBadge tone="warning">разработка</StatusBadge>}
      />
      <main className="min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)] md:py-[var(--s-7)]">
        <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-[var(--s-5)]">
          <h1 className="text-lg font-medium">Правила</h1>
          <p className="max-w-[80ch] text-sm text-muted">
            Реестр инженерных правил рабочего пространства. В расчёт идёт только утверждённая
            действующая версия; утверждённая версия не меняется — изменение оформляется новой
            версией.
          </p>
          <CalcRules />
        </div>
      </main>
    </>
  );
};

export default CalcRulesPage;
