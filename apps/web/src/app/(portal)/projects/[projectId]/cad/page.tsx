'use client';

import { Suspense, use } from 'react';

import { CadScreen } from '@/components/cad/CadScreen';
import { TopBar } from '@/components/shell/TopBar';
import { EmptyState, SkeletonRows, StatusBadge } from '@/components/ui';
import { cadAccess } from '@/lib/cad/access';
import { useFeatures, useMeta, useProject } from '@/lib/queries';

/**
 * PDF → CAD (QA-контур, флаг `cad.export`).
 *
 * Закрыто флагом: при выключенном флаге страницы нет. Результат — кандидат движка, не
 * инженерная приёмка. Выбор ревизии, задания и вида хранится в адресе.
 */

interface IPageProps {
  params: Promise<{ projectId: string }>;
}

const CadPage = ({ params }: IPageProps) => {
  const { projectId } = use(params);
  const meta = useMeta();
  const access = cadAccess(meta.isSuccess, useFeatures());
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
          { label: 'PDF → CAD' },
        ]}
        status={<StatusBadge tone="warning">QA · кандидат движка</StatusBadge>}
      />
      <main className="min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)] md:py-[var(--s-7)]">
        {/* useSearchParams требует границы приостановки (иначе маршрут не предрендерить). */}
        <Suspense fallback={<SkeletonRows rows={6} />}>
          <CadScreen projectId={projectId} />
        </Suspense>
      </main>
    </>
  );
};

export default CadPage;
