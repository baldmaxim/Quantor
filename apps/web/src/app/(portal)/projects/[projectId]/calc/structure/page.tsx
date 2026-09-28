'use client';

import { use } from 'react';

import { CalcStructure } from '@/components/calc/CalcStructure';
import { TopBar } from '@/components/shell/TopBar';
import { EmptyState, SkeletonRows, StatusBadge } from '@/components/ui';
import { calcAccess } from '@/lib/calc/access';
import { useFeatures, useMeta, useProject } from '@/lib/queries';

/**
 * Расчёты → Структура системы (ADR-0030, PROMPT 05).
 *
 * Закрыто флагом `calc.portal`. Логическая структура системы после расчёта: наблюдённое,
 * рассчитанное, синтезированное и принятое допущением — отдельно; что пока не известно — явно.
 */

interface IPageProps {
  params: Promise<{ projectId: string }>;
}

const CalcStructurePage = ({ params }: IPageProps) => {
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
          { label: 'Структура системы' },
        ]}
        status={<StatusBadge tone="warning">разработка · только чтение</StatusBadge>}
      />
      <main className="min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)] md:py-[var(--s-7)]">
        <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-[var(--s-5)]">
          <h1 className="text-lg font-medium">Структура системы</h1>
          <p className="max-w-[80ch] text-sm text-muted">
            Структура стадии П — расчётная гипотеза, а не рабочая документация: координат и трасс
            здесь нет, диапазоны остаются диапазонами, а выбор делает утверждённое правило или
            инженер.
          </p>
          <CalcStructure projectId={projectId} />
        </div>
      </main>
    </>
  );
};

export default CalcStructurePage;
