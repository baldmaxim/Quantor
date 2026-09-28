'use client';

import { use } from 'react';

import { CalcInputs } from '@/components/calc/CalcInputs';
import { TopBar } from '@/components/shell/TopBar';
import { ButtonLink, EmptyState, SkeletonRows, StatusBadge } from '@/components/ui';
import { calcAccess } from '@/lib/calc/access';
import { useFeatures, useMeta, useProject } from '@/lib/queries';

/**
 * Расчёты → Исходные данные (ADR-0030, PROMPT 02).
 *
 * Закрыто флагом `calc.portal`: при выключенном флаге страницы нет. Расчёта систем здесь ещё
 * нет — только то, что известно для него, и то, чего не хватает.
 */

interface IPageProps {
  params: Promise<{ projectId: string }>;
}

const CalcPage = ({ params }: IPageProps) => {
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
          { label: 'Расчёты' },
        ]}
        status={<StatusBadge tone="warning">разработка · расчёта ещё нет</StatusBadge>}
        actions={
          <>
            <ButtonLink href={`/projects/${projectId}/calc/runs`} transitionTypes={['nav-forward']}>
              Запуски
            </ButtonLink>
            <ButtonLink
              href={`/projects/${projectId}/calc/structure`}
              transitionTypes={['nav-forward']}
            >
              Структура
            </ButtonLink>
            <ButtonLink
              href={`/projects/${projectId}/calc/rules`}
              transitionTypes={['nav-forward']}
            >
              Правила
            </ButtonLink>
          </>
        }
      />
      <main className="min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)] md:py-[var(--s-7)]">
        <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-[var(--s-5)]">
          <h1 className="text-lg font-medium">Исходные данные</h1>
          <p className="max-w-[80ch] text-sm text-muted">
            Что известно для расчёта систем ВК стадии П и чего не хватает. «Не найдено» — все
            распознанные документы проверены; «не проверено» — документ ещё не смотрели. ВОР
            Заказчика в расчёт не идёт.
          </p>
          <CalcInputs projectId={projectId} />
        </div>
      </main>
    </>
  );
};

export default CalcPage;
