'use client';

import type { CadBuilding3dFloorRead } from '@quantor/api-client';
import { useQueryClient } from '@tanstack/react-query';
import { usePathname, useRouter, useSearchParams } from 'next/navigation';
import { Suspense, use } from 'react';

import { TopBar } from '@/components/shell/TopBar';
import { EmptyState, SkeletonRows } from '@/components/ui';
import type { IBuildingViewerSelection } from '@/components/projects/building3d/BuildingViewer';
import { BuildingViewerLazy } from '@/components/projects/building3d/BuildingViewerLazy';
import { cadAccess } from '@/lib/cad/access';
import { resolveSheetPosition, useCadBuilding3dWalls } from '@/lib/cad/building3d-queries';
import { workspaceCadHref } from '@/lib/cad/workspace-url';
import { useFeatures, useMeta, useProject } from '@/lib/queries';

/**
 * «3D: общий вид объекта» — просмотрщик здания из стен всех этажей. Закрыта флагом `cad.export`
 * (как и вкладка CAD): при выключенном флаге страницы нет, пока мета не пришла — заглушка.
 * Здание (`group`, `all` - весь объект), выбранный этаж, детальный вид и конструкция живут в адресе
 * (`?group=…&floor=<ключ этажа>&detail=1&construction=<id>`), ссылку можно переслать; лист этажа в рабочей области открывает отдельная кнопка.
 */

interface IPageProps {
  params: Promise<{ projectId: string }>;
}

const SHELL = 'min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)]';

const Building3dPage = ({ params }: IPageProps) => {
  const { projectId } = use(params);
  const router = useRouter();
  const pathname = usePathname();
  const searchParams = useSearchParams();
  const queryClient = useQueryClient();
  const meta = useMeta();
  const access = cadAccess(meta.isSuccess, useFeatures());
  const project = useProject(projectId);
  // Данные здания грузятся параллельно с чанком просмотрщика: тот же ключ, просмотрщик берёт их из кэша.
  useCadBuilding3dWalls(projectId, access === 'open');

  const selection: IBuildingViewerSelection = {
    group: searchParams.get('group'),
    floor: searchParams.get('floor'),
    detail: searchParams.get('detail') === '1',
    construction: searchParams.get('construction'),
  };

  const changeSelection = (next: IBuildingViewerSelection): void => {
    const params = new URLSearchParams(searchParams.toString());
    if (next.group === null) params.delete('group');
    else params.set('group', next.group);
    if (next.floor === null) params.delete('floor');
    else params.set('floor', next.floor);
    if (next.floor !== null && next.detail) params.set('detail', '1');
    else params.delete('detail');
    if (next.floor !== null && next.construction !== null) params.set('construction', next.construction);
    else params.delete('construction');
    const query = params.toString();
    router.replace(query === '' ? pathname : `${pathname}?${query}`, { scroll: false });
  };

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
          <BuildingViewerLazy
            projectId={projectId}
            selection={selection}
            onSelectionChange={changeSelection}
            onOpenSheet={(floor) => void openFloor(floor)}
          />
        </main>
      )}
    </>
  );
};

// `useSearchParams` требует границы Suspense: иначе страницу нельзя отдать статической оболочкой.
const Building3dRoute = ({ params }: IPageProps) => (
  <Suspense fallback={null}>
    <Building3dPage params={params} />
  </Suspense>
);

export default Building3dRoute;
