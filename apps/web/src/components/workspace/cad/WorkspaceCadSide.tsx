'use client';

import { useEffect, useRef, useState, type FC, type ReactNode } from 'react';

import { CadJobDetail } from '@/components/cad/CadJobDetail';
import { CadJobList } from '@/components/cad/CadJobList';
import { CadFinishPanel } from '@/components/cad/finishes/CadFinishPanel';
import { CadMepPanel } from '@/components/cad/mep/CadMepPanel';
import { CadRisersPanel } from '@/components/cad/risers/CadRisersPanel';
import { CadResult } from '@/components/cad/CadResult';
import { CadFilesSection } from '@/components/cad/viewer/CadFilesSection';
import { CadLayersPanel } from '@/components/cad/viewer/CadLayersPanel';
import { CadRemarksPanel } from '@/components/cad/viewer/CadRemarksPanel';
import { CadScaleSection } from '@/components/cad/viewer/CadScaleSection';
import { CadSidePanel, type ICadSideTab } from '@/components/cad/viewer/CadSidePanel';
import { CadViewHeader } from '@/components/cad/viewer/CadViewHeader';
import { CadZonesPanel } from '@/components/cad/viewer/CadZonesPanel';
import { Button, ErrorState, Skeleton, SkeletonRows } from '@/components/ui';
import { formatFloorTitle, formatFloorTitleFull } from '@/lib/cad/floor-title';

import { CadSectionsPanel } from './CadSectionsPanel';
import { CadUpdateBanner } from './CadUpdateBanner';
import { ConstructionsPanel } from './ConstructionsPanel';
import type { IWorkspaceCadLeftProps, IWorkspaceCadSideProps } from './types';

/** Список заданий ревизии: раздел «Задания» (выбор задания переводит рабочую область на его лист). */
export interface IWorkspaceCadSideJobs {
  readonly jobs?: Pick<
    IWorkspaceCadLeftProps,
    'projectId' | 'revisionId' | 'selectedJobId' | 'onSelectJob'
  > | null;
}

/** Управление открытым разделом снаружи: страница открывает раздел по действию окна «Обработка». */
export interface IWorkspaceCadSidePipeline {
  /** Открытый раздел, которым владеет страница; нет - раздел хранится в панели. */
  readonly sideTab?: string | null;
  readonly onSideTabChange?: (id: string) => void;
}

const HINT = 'p-[var(--s-5)] text-xs text-muted';

/**
 * Правая панель вкладки CAD: слои, замечания, масштаб, файлы (с результатом), трассы механики и
 * задание листа рабочей области.
 *
 * Раздел «Зоны» - разметка помещений и дверей листа - есть и у листа без задания.
 * Раздел «Отделка» (ADR-0042) - шаблоны проекта и ведомость листа - стоит сразу после «Зон».
 * Раздел «Конструкции» (кладка и монолит, ADR-0038) - у листа с видом.
 * Раздел «Разрезы» (уровни по разрезам АР) - только у страницы-разреза, первый и открыт по умолчанию;
 * у листа без вида тоже. Со страниц плана разрезы открывают из блока «Высота из разрезов» в «Трассах».
 * Раздел «Задания» (список заданий ревизии) - последний, если передан `jobs`.
 * Показано только задание открытого листа; более новое неготовое (`update`) - плашкой сверху. С идущим или упавшим заданием - только раздел
 * «Задание»: диагностики вида у него нет. Ширину и сворачивание панели ведёт каркас рабочей области.
 */
export const WorkspaceCadSide: FC<
  IWorkspaceCadSideProps & IWorkspaceCadSideJobs & IWorkspaceCadSidePipeline
> = ({
  state,
  sheetLabel,
  floorTitle = null,
  loadError,
  onRetry,
  job,
  update = null,
  viewLoading,
  viewError,
  view,
  zones = null,
  constructions = null,
  finishes = null,
  sections = null,
  jobs = null,
  sideTab: sideTabProp = null,
  onSideTabChange,
}) => {
  // Раздел живёт здесь (или у страницы): при переходе на другой лист панель остаётся на выбранном
  // разделе. Пока раздел не выбран, открыты «Слои».
  const [innerTab, setInnerTab] = useState<string | null>(null);
  // Вкладка «Разрезы» есть только на странице-разрезе и там открыта по умолчанию.
  const isSectionPage = sections?.isSectionPage ?? false;
  const sideTab = sideTabProp ?? innerTab ?? (isSectionPage ? 'sections' : 'layers');
  const setSideTab = (id: string) => {
    setInnerTab(id);
    onSideTabChange?.(id);
  };
  // Переход на страницу-разрез (ссылка из «Трасс») открывает «Разрезы», даже если раздел выбирали.
  const sectionsPage = sections?.pageIndex ?? null;
  const [prevPage, setPrevPage] = useState(sectionsPage);
  if (prevPage !== sectionsPage) {
    setPrevPage(sectionsPage);
    if (isSectionPage) setInnerTab('sections');
  }
  const prevPageRef = useRef(sectionsPage);
  useEffect(() => {
    if (prevPageRef.current === sectionsPage) return;
    prevPageRef.current = sectionsPage;
    // Раздел, которым владеет страница, переключаем её же колбэком.
    if (isSectionPage) onSideTabChange?.('sections');
  }, [sectionsPage, isSectionPage, onSideTabChange]);

  if (state === 'no-sheet') return <p className={HINT}>Лист не выбран.</p>;

  if (state === 'loading') {
    return (
      <div className="p-[var(--s-5)]" role="status" aria-label="Загрузка заданий CAD">
        <SkeletonRows rows={3} />
      </div>
    );
  }

  if (state === 'error') {
    return (
      <div role="alert" className="flex flex-col gap-[var(--s-3)] p-[var(--s-5)] text-xs text-danger">
        <span>Не удалось загрузить задания CAD. {loadError}</span>
        <Button compact onClick={onRetry} className="self-start max-md:h-[44px]">
          Повторить
        </Button>
      </div>
    );
  }

  const zonesTab: ICadSideTab | null = zones
    ? { id: 'zones', label: 'Зоны', content: <CadZonesPanel {...zones} /> }
    : null;

  // Раздел «Отделка»: шаблоны проекта и ведомость листа; зону на листе выделяют через «Зоны».
  const finishTab: ICadSideTab | null =
    finishes && zones
      ? {
          id: 'finishes',
          label: 'Отделка',
          content: (
            <CadFinishPanel
              projectId={finishes.projectId}
              revisionId={finishes.revisionId}
              pageIndex={finishes.pageIndex}
              // Ведомость считается на сервере: раздел читает её, только пока открыт.
              load={finishes.load && sideTab === 'finishes'}
              activeId={zones.activeId}
              onActivate={zones.onActivate}
            />
          ),
        }
      : null;

  // Раздел «Разрезы» работает по PDF ревизии и не требует преобразования листа в CAD; он есть
  // только у страницы-разреза и стоит первым. С планов разрезы открывают из запуска трасс.
  const sectionsTab: ICadSideTab | null = sections?.isSectionPage
    ? { id: 'sections', label: 'Разрезы', content: <CadSectionsPanel {...sections} /> }
    : null;

  // Раздел «Задания» - очередь и история заданий ревизии; всегда последний.
  const jobsTab: ICadSideTab | null = jobs
    ? {
        id: 'jobs',
        label: 'Задания',
        content: (
          <CadJobList
            // Ключ по ревизии: список другого документа не переиспользуется.
            key={jobs.revisionId}
            projectId={jobs.projectId}
            revisionId={jobs.revisionId}
            selectedJobId={jobs.selectedJobId}
            onSelect={jobs.onSelectJob}
          />
        ),
      }
    : null;

  // Обновление CAD листа: плашка над панелью, прежний результат остаётся на экране.
  const withUpdate = (panel: ReactNode) =>
    update !== null ? (
      <>
        <CadUpdateBanner update={update} />
        {panel}
      </>
    ) : (
      panel
    );

  if (state === 'none' || job === null) {
    const none = (
      <div className="flex flex-col gap-[var(--s-3)] p-[var(--s-5)]" data-testid="workspace-cad-none">
        {sheetLabel !== null && (
          <p className="text-xs text-muted">
            {floorTitle !== null && formatFloorTitle(floorTitle, '') !== '' && (
              <>
                <span className="text-text" title={formatFloorTitleFull(floorTitle) ?? undefined}>
                  {formatFloorTitle(floorTitle, '')}
                </span>
                {' · '}
              </>
            )}
            Лист <span className="text-text">{sheetLabel}</span>
          </p>
        )}
        <p className="text-sm">Лист не преобразовывался</p>
        <p className="text-xs text-muted">
          Запустите преобразование: нажмите статус листа вверху справа, результат появится здесь.
        </p>
      </div>
    );
    // Зоны размечают и лист без задания: эталон для движка нужен до преобразования.
    if (zonesTab === null && sectionsTab === null && jobsTab === null) return none;
    return withUpdate(
      <CadSidePanel
        label="Панель CAD"
        tabs={[
          ...(sectionsTab ? [sectionsTab] : []),
          { id: 'job', label: 'Задание', content: none },
          ...(zonesTab ? [zonesTab] : []),
          ...(finishTab ? [finishTab] : []),
          ...(jobsTab ? [jobsTab] : []),
        ]}
        active={sideTab}
        onActiveChange={setSideTab}
      />,
    );
  }

  const jobTab: ICadSideTab = {
    id: 'job',
    label: 'Задание',
    content: (
      <div className="flex min-w-0 flex-col gap-[var(--s-6)]">
        {viewLoading && (
          <div className="flex flex-col gap-[var(--s-3)]" role="status" aria-label="Загрузка вида">
            <Skeleton className="h-[20px] w-[60%]" />
            <Skeleton className="h-[16px] w-[80%]" />
          </div>
        )}
        {viewError && (
          <ErrorState
            title="Результат CAD не загружен"
            code={viewError.code}
            description={viewError.text}
          />
        )}
        {view && <CadViewHeader diagnostics={view.diagnostics} />}
        <CadJobDetail
          // Ключ по заданию: попытка, выбранная вручную, не переходит на другое задание.
          key={`${job.revisionId}:${job.jobId}`}
          projectId={job.projectId}
          revisionId={job.revisionId}
          jobId={job.jobId}
          selectedPage={job.page}
          selectedView={job.view}
          onSelectView={job.onSelectView}
        />
      </div>
    ),
  };

  const tabs: readonly ICadSideTab[] = view
    ? [
        ...(sectionsTab ? [sectionsTab] : []),
        {
          id: 'layers',
          label: 'Слои',
          content: <CadLayersPanel {...view.layers} />,
        },
        {
          id: 'remarks',
          label: 'Замечания',
          content: view.remarks ? <CadRemarksPanel {...view.remarks} /> : null,
        },
        {
          id: 'scale',
          label: 'Масштаб',
          content: <CadScaleSection scale={view.diagnostics.scale} />,
        },
        {
          id: 'files',
          label: 'Файлы',
          content: (
            <div className="flex min-w-0 flex-col gap-[var(--s-6)]">
              {job.detail && (
                <CadResult
                  projectId={job.projectId}
                  revisionId={job.revisionId}
                  job={job.detail}
                  // Файлы принадлежат попытке с результатом; без неё - текущей.
                  attempt={job.detail.result_attempt ?? job.detail.attempt}
                />
              )}
              <CadFilesSection
                projectId={job.projectId}
                revisionId={job.revisionId}
                jobId={job.jobId}
                diagnostics={view.diagnostics}
              />
            </div>
          ),
        },
        ...(view.mep
          ? [
              { id: 'mep', label: 'Трассы', content: <CadMepPanel {...view.mep} /> },
              // Реестр стояков по ИОС - вход построения трасс (ADR-0041), рядом с «Трассами».
              {
                id: 'risers',
                label: 'Стояки',
                content: <CadRisersPanel parent={view.mep.parent} />,
              },
            ]
          : []),
        ...(zonesTab ? [zonesTab] : []),
        ...(finishTab ? [finishTab] : []),
        ...(constructions
          ? [
              {
                id: 'constructions',
                label: 'Конструкции',
                content: <ConstructionsPanel {...constructions} />,
              },
            ]
          : []),
        jobTab,
        ...(jobsTab ? [jobsTab] : []),
      ]
    : [
        ...(sectionsTab ? [sectionsTab] : []),
        ...(zonesTab ? [zonesTab] : []),
        ...(finishTab ? [finishTab] : []),
        jobTab,
        ...(jobsTab ? [jobsTab] : []),
      ];

  return withUpdate(
    <CadSidePanel label="Панель CAD" tabs={tabs} active={sideTab} onActiveChange={setSideTab} />,
  );
};
