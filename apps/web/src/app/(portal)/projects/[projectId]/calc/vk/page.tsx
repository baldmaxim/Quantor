'use client';

import { use } from 'react';

import { CalcVk } from '@/components/calc/CalcVk';
import { TopBar } from '@/components/shell/TopBar';
import { EmptyState, SkeletonRows, StatusBadge } from '@/components/ui';
import { calcAccess } from '@/lib/calc/access';
import { useFeatures, useMeta, useProject } from '@/lib/queries';

/**
 * Расчёты → ВК (ADR-0030, PROMPT 06).
 *
 * Закрыто флагом `calc.portal`: он выключен до реального инженерного гейта и решения
 * владельца. Паспорт — оценка стадии П, а не ВОР и не смета; сверки с ВОР здесь нет.
 */

interface IPageProps {
  params: Promise<{ projectId: string }>;
}

const CalcVkPage = ({ params }: IPageProps) => {
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
          { label: 'ВК' },
        ]}
        status={<StatusBadge tone="warning">разработка · до инженерного гейта</StatusBadge>}
      />
      <main className="min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)] md:py-[var(--s-7)]">
        <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-[var(--s-5)]">
          <h1 className="text-lg font-medium">Расчёт ВК стадии П</h1>
          <p className="max-w-[80ch] text-sm text-muted">
            Независимая инженерная оценка В1, Т3, Т4, К1 по документации стадии П: что найдено, что
            рассчитано, какие объёмы следуют из структуры и что пока не определено. Диапазон
            остаётся диапазоном, неизвестное — «не определено», а не ноль.
          </p>
          <CalcVk projectId={projectId} />
        </div>
      </main>
    </>
  );
};

export default CalcVkPage;
