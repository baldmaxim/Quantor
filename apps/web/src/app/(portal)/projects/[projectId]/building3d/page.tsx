'use client';

import type { CadBuilding3dFloorRead } from '@quantor/api-client';
import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { use } from 'react';

import { TopBar } from '@/components/shell/TopBar';
import { EmptyState, SkeletonRows } from '@/components/ui';
import { CadBuilding3dLazy } from '@/components/workspace/cad/building3d/CadBuilding3dLazy';
import { cadAccess } from '@/lib/cad/access';
import { resolveSheetPosition } from '@/lib/cad/building3d-queries';
import { workspaceCadHref } from '@/lib/cad/workspace-url';
import { useFeatures, useMeta, useProject } from '@/lib/queries';

/**
 * «3D: общий вид объекта» — колонка «Здание» на всю страницу. Закрыта флагом `cad.export`
 * (как и вкладка CAD): при выключенном флаге страницы нет, пока мета не пришла — заглушка.
 * Щелчок по этажу открывает лист этажа в рабочей области (вкладка CAD).
 */

interface IPageProps {
  params: Promise<{ projectId: string }>;
}

const SHELL = 'min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)]';

const Building3dPage = ({ params }: IPageProps) => {
  const { projectId } = use(params);
  const router = useRouter();
  const queryClient = useQueryClient();
  const meta = useMeta();
  const access = cadAccess(meta.isSuccess, useFeatures());
  const project = useProject(projectId);

  const openFloor = async (floor: CadBuilding3dFloorRead): Promise<void> => {
    const position = await resolveSheetPosition(queryClient, floor.revision_id, floor.page_index);
    router.push(
      workspaceCadHref(projectId, {
        revision: floor.revision_id,
        position,
        job: floor.job_id,
        view: floor.view,
      }),
    );
  };

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
          { label: '3D: общий вид объекта' },
        ]}
      />
      {access === 'pending' ? (
        <main className={SHELL}>
          <SkeletonRows rows={6} />
        </main>
      ) : (
        <main className="flex min-h-0 min-w-0 flex-1 flex-col overflow-hidden bg-bg">
          <CadBuilding3dLazy
            projectId={projectId}
            current={null}
            layout="page"
            onSelectFloor={(floor) => void openFloor(floor)}
          />
        </main>
      )}
    </>
  );
};

export default Building3dPage;
