'use client';

import { use } from 'react';

import { TenderVersionsScreen } from '@/components/versions/TenderVersionsScreen';
import { TopBar } from '@/components/shell/TopBar';
import { EmptyState, SkeletonRows, StatusBadge } from '@/components/ui';
import { useFeatures, useMeta, useProject } from '@/lib/queries';
import { versionsAccess } from '@/lib/tender-versions';

/**
 * Версии тендера (ADR-0035, этап M2).
 *
 * Закрыто пилотным флагом `tender.versions` и в интерфейсе, и на сервере (ADR-0023).
 * Версия — замороженный комплект ревизий документов проекта: ответ на вопрос «по каким
 * чертежам». Запись в HUBTender портал не выполняет.
 */

interface IPageProps {
  params: Promise<{ projectId: string }>;
}

const TenderVersionsPage = ({ params }: IPageProps) => {
  const { projectId } = use(params);
  const meta = useMeta();
  const access = versionsAccess(meta.isSuccess, useFeatures());
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
          { label: 'Версии тендера' },
        ]}
        status={<StatusBadge tone="warning">пилот</StatusBadge>}
      />
      <main className="min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)] md:py-[var(--s-7)]">
        <div className="mx-auto flex w-full max-w-[1400px] flex-col gap-[var(--s-5)]">
          <p className="max-w-[80ch] text-sm text-muted">
            Версия — замороженный комплект ревизий документов проекта. После заморозки состав не
            меняется: новый комплект — новая версия. Связь с HUBTender только читается, в HUBTender
            портал ничего не пишет.
          </p>
          <TenderVersionsScreen projectId={projectId} />
        </div>
      </main>
    </>
  );
};

export default TenderVersionsPage;
