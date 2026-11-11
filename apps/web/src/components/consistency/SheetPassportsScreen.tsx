'use client';

import type { FC } from 'react';

import { TopBar } from '@/components/shell/TopBar';
import { EmptyState, SkeletonRows } from '@/components/ui';
import { consistencyAccess } from '@/lib/consistency/access';
import { useFeatures, useMeta, useProject } from '@/lib/queries';

import { SheetPassportsView } from './SheetPassportsView';

/**
 * Экран «Листы комплекта» (ADR-0043, С1). Закрыт флагом `project.consistency`: при выключенном
 * флаге страницы нет, пока мета не пришла — заглушка загрузки.
 */

interface IScreenProps {
  readonly projectId: string;
}

const MAIN = 'min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)]';

export const SheetPassportsScreen: FC<IScreenProps> = ({ projectId }) => {
  const meta = useMeta();
  const access = consistencyAccess(meta.isSuccess, useFeatures());
  const project = useProject(projectId);

  if (access === 'pending') {
    return (
      <main className={MAIN}>
        <SkeletonRows rows={6} />
      </main>
    );
  }

  if (access === 'hidden') {
    return (
      <main className={MAIN}>
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
          { label: 'Листы комплекта' },
        ]}
      />
      <main className={`${MAIN} md:py-[var(--s-7)]`}>
        <div className="mx-auto flex w-full max-w-[1600px] flex-col gap-[var(--s-5)]">
          <p className="max-w-[80ch] text-sm text-muted">
            Паспорта страниц PDF проекта: раздел, тип листа, стадия, корпус, секция, этажи, отметка
            и шифр. Разбор даёт кандидатов — подтверждает человек. «—» значит «не найдено».
          </p>
          <SheetPassportsView projectId={projectId} />
        </div>
      </main>
    </>
  );
};
