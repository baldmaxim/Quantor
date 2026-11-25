'use client';

import { use } from 'react';

import { ModelScreen } from '@/components/projects/model/ModelScreen';
import { ProjectNextStep } from '@/components/projects/ProjectSteps';
import { TopBar } from '@/components/shell/TopBar';
import { EmptyState, SkeletonRows } from '@/components/ui';
import { modelAccess } from '@/lib/model/model-access';
import { useFeatures, useMeta, useProject } from '@/lib/queries';

/**
 * «Модель здания» — версии пакета QMP проекта и 3D этажа (ADR-0053). Закрыта флагом `model.import`:
 * при выключенном флаге страницы нет, пока мета не пришла — каркас.
 */

interface IPageProps {
  params: Promise<{ projectId: string }>;
}

const SHELL = 'min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)]';

const ModelPage = ({ params }: IPageProps) => {
  const { projectId } = use(params);
  const meta = useMeta();
  const access = modelAccess(meta.isSuccess, useFeatures());
  const project = useProject(projectId);

  if (access === 'hidden') {
    return (
      <main className={SHELL}>
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
          { label: 'Модель здания' },
        ]}
        actions={<ProjectNextStep projectId={projectId} current="model" />}
      />
      {access === 'pending' ? (
        <main className={SHELL}>
          <SkeletonRows rows={6} />
        </main>
      ) : (
        <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-bg">
          <ModelScreen projectId={projectId} />
        </main>
      )}
    </>
  );
};

export default ModelPage;
