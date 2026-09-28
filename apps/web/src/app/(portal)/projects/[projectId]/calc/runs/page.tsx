'use client';

import { use } from 'react';

import { CalcRuns } from '@/components/calc/CalcRuns';
import { TopBar } from '@/components/shell/TopBar';
import { EmptyState, SkeletonRows, StatusBadge } from '@/components/ui';
import { calcAccess } from '@/lib/calc/access';
import { useFeatures, useMeta, useProject } from '@/lib/queries';

/**
 * Расчёты → Запуски (ADR-0030, PROMPT 04).
 *
 * Закрыто флагом `calc.portal`. Запуски проекта, причины блокировки и «Почему такое значение?».
 * Реальных калькуляторов систем ещё нет — только демонстрационный.
 */

interface IPageProps {
  params: Promise<{ projectId: string }>;
}

const CalcRunsPage = ({ params }: IPageProps) => {
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
          { label: 'Запуски' },
        ]}
        status={<StatusBadge tone="warning">разработка · только чтение</StatusBadge>}
      />
      <main className="min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)] md:py-[var(--s-7)]">
        <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-[var(--s-5)]">
          <h1 className="text-lg font-medium">Запуски</h1>
          <p className="max-w-[80ch] text-sm text-muted">
            Каждый запуск считается по неизменяемому снимку фактов и точным версиям правил:
            исправление данных — это новый запуск, старый не меняется. Нехватка данных —
            «заблокировано» с причинами, а не ноль.
          </p>
          <CalcRuns projectId={projectId} />
        </div>
      </main>
    </>
  );
};

export default CalcRunsPage;
