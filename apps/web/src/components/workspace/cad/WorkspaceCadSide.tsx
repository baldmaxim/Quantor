'use client';

import { useEffect, useRef, useState, type FC, type ReactNode } from 'react';

import { CadFinishPanel } from '@/components/cad/finishes/CadFinishPanel';
import { CadMepPanel } from '@/components/cad/mep/CadMepPanel';
import { CadRisersPanel } from '@/components/cad/risers/CadRisersPanel';
import { CadLayersPanel } from '@/components/cad/viewer/CadLayersPanel';
import { CadRemarksPanel } from '@/components/cad/viewer/CadRemarksPanel';
import { CadSidePanel, type ICadSideTab } from '@/components/cad/viewer/CadSidePanel';
import { CadZonesPanel } from '@/components/cad/viewer/CadZonesPanel';
import { CadZonesQuality } from '@/components/cad/viewer/CadZonesQuality';
import { Button, SkeletonRows } from '@/components/ui';

import { CadFacadesPanel } from './CadFacadesPanel';
import { CadSectionsPanel } from './CadSectionsPanel';
import { CadUpdateBanner } from './CadUpdateBanner';
import { ConstructionsPanel } from './ConstructionsPanel';
import type { IWorkspaceCadSideProps } from './types';
import { WorkspaceCadSheetTab, type WorkspaceCadSheetJobs } from './WorkspaceCadSheetTab';

/** Список заданий ревизии: блок «Задания документа» раздела «Лист». */
export interface IWorkspaceCadSideJobs {
  readonly jobs?: WorkspaceCadSheetJobs | null;
}

/** Управление открытым разделом снаружи: страница открывает раздел по действию окна «Обработка». */
export interface IWorkspaceCadSidePipeline {
  /** Открытый раздел, которым владеет страница; нет - раздел хранится в панели. */
  readonly sideTab?: string | null;
  readonly onSideTabChange?: (id: string) => void;
}

const HINT = 'p-[var(--s-5)] text-xs text-muted';

/**
 * Правая панель вкладки CAD. Состав и порядок разделов один для любого состояния листа,
 * отсутствующие пропускаются: «Разрезы», «Слои», «Зоны», «Конструкции», «Отделка», «Трассы»,
 * «Фасады», «Замечания», «Лист».
 *
 * «Разрезы» (уровни по разрезам АР) - только у страницы-разреза, первый и открыт по умолчанию.
 * «Слои», «Конструкции» (ADR-0038), «Трассы» (с реестром стояков внутри) и «Замечания» - у листа с
 * видом. «Зоны» и «Отделка» (ADR-0042) есть и у листа без задания. «Лист» - всегда последний:
 * сводка вида, масштаб, файлы, ход преобразования, профиль оформления и задания документа.
 * Показано только задание открытого листа; более новое неготовое (`update`) - плашкой сверху.
 * Ширину и сворачивание панели ведёт каркас рабочей области.
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
  facades = null,
  style = null,
  jobs = null,
  sideTab: sideTabProp = null,
  onSideTabChange,
}) => {
  // Раздел живёт здесь (или у страницы): при переходе на другой лист панель остаётся на выбранном
  // разделе. Пока раздел не выбран, открыты «Слои».
  const [innerTab, setInnerTab] = useState<string | null>(null);
  // Вкладка «Разрезы» есть только на странице-разрезе и там открыта по умолчанию.
  const isSectionPage = sections?.isSectionPage ?? false;
  const wantedTab = sideTabProp ?? innerTab ?? (isSectionPage ? 'sections' : 'layers');
  // Набор разделов считается из флагов заранее: от открытого раздела зависит чтение ведомостей.
  const shownView = state !== 'none' && job !== null ? view : null;
  const hasFinishes = finishes !== null && zones !== null;
  const tabIds: readonly string[] = [
    ...(isSectionPage ? ['sections'] : []),
    ...(shownView ? ['layers'] : []),
    ...(zones ? ['zones'] : []),
    ...(shownView && constructions ? ['constructions'] : []),
    ...(hasFinishes ? ['finishes'] : []),
    ...(shownView?.mep ? ['mep'] : []),
    ...(facades ? ['facades'] : []),
    ...(shownView ? ['remarks'] : []),
    'job',
  ];
  // Желаемого раздела у этого листа нет: с видом открыты «Слои», без вида - «Лист».
  const sideTab = tabIds.includes(wantedTab) ? wantedTab : shownView ? 'layers' : 'job';
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
    ? {
        id: 'zones',
        label: 'Зоны',
        content: (
          <div className="flex min-w-0 flex-col gap-[var(--s-4)]">
            {finishes && finishes.revisionId !== null && finishes.pageIndex !== null && (
              <CadZonesQuality
                projectId={finishes.projectId}
                revisionId={finishes.revisionId}
                pageIndex={finishes.pageIndex}
                load={finishes.load && sideTab === 'zones'}
                zones={zones.zones}
                activeId={zones.activeId}
                onActivate={zones.onActivate}
                recreate={zones.autoZones ?? null}
              />
            )}
            <CadZonesPanel {...zones} />
          </div>
        ),
      }
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
              onOpenTab={setSideTab}
            />
          ),
        }
      : null;

  // Раздел «Разрезы» работает по PDF ревизии и не требует преобразования листа в CAD; он есть
  // только у страницы-разреза и стоит первым. С планов разрезы открывают из запуска трасс.
  const sectionsTab: ICadSideTab | null = sections?.isSectionPage
    ? { id: 'sections', label: 'Разрезы', content: <CadSectionsPanel {...sections} /> }
    : null;

  // Раздел «Фасады» (ADR-0048) работает по PDF ревизии; есть у любого листа при флаге `cad.export`.
  const facadesTab: ICadSideTab | null = facades
    ? { id: 'facades', label: 'Фасады', content: <CadFacadesPanel {...facades} /> }
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

  const sheet = (
    <WorkspaceCadSheetTab
      sheetLabel={sheetLabel}
      floorTitle={floorTitle}
      job={state === 'none' ? null : job}
      viewLoading={viewLoading}
      viewError={viewError}
      view={shownView}
      style={style}
      jobs={jobs}
    />
  );

  // Лист без задания и без других разделов: одна подсказка, вкладки не нужны.
  if ((state === 'none' || job === null) && tabIds.length === 1 && !style && !jobs) {
    return <div className="p-[var(--s-5)]">{sheet}</div>;
  }

  const tabs: readonly ICadSideTab[] = [
    ...(sectionsTab ? [sectionsTab] : []),
    ...(shownView
      ? [{ id: 'layers', label: 'Слои', content: <CadLayersPanel {...shownView.layers} /> }]
      : []),
    ...(zonesTab ? [zonesTab] : []),
    ...(shownView && constructions
      ? [
          {
            id: 'constructions',
            label: 'Конструкции',
            content: <ConstructionsPanel {...constructions} />,
          },
        ]
      : []),
    ...(finishTab ? [finishTab] : []),
    ...(shownView?.mep
      ? [
          {
            id: 'mep',
            label: 'Трассы',
            content: (
              <CadMepPanel
                {...shownView.mep}
                // Реестр стояков по ИОС - вход построения трасс (ADR-0041).
                risers={<CadRisersPanel parent={shownView.mep.parent} />}
              />
            ),
          },
        ]
      : []),
    ...(facadesTab ? [facadesTab] : []),
    ...(shownView
      ? [
          {
            id: 'remarks',
            label: 'Замечания',
            content: shownView.remarks ? <CadRemarksPanel {...shownView.remarks} /> : null,
          },
        ]
      : []),
    { id: 'job', label: 'Лист', content: sheet },
  ];

  return withUpdate(
    <CadSidePanel label="Панель CAD" tabs={tabs} active={sideTab} onActiveChange={setSideTab} />,
  );
};
