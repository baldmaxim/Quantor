'use client';

import { useState, type FC } from 'react';

import { CadJobDetail } from '@/components/cad/CadJobDetail';
import { CadMepPanel } from '@/components/cad/mep/CadMepPanel';
import { CadResult } from '@/components/cad/CadResult';
import { CadFilesSection } from '@/components/cad/viewer/CadFilesSection';
import { CadLayersPanel } from '@/components/cad/viewer/CadLayersPanel';
import { CadRemarksPanel } from '@/components/cad/viewer/CadRemarksPanel';
import { CadScaleSection } from '@/components/cad/viewer/CadScaleSection';
import { CadSidePanel, type ICadSideTab } from '@/components/cad/viewer/CadSidePanel';
import { CadViewHeader } from '@/components/cad/viewer/CadViewHeader';
import { CadZonesPanel } from '@/components/cad/viewer/CadZonesPanel';
import { Button, ErrorState, Skeleton, SkeletonRows } from '@/components/ui';

import { ConstructionsPanel } from './ConstructionsPanel';
import type { IWorkspaceCadSideProps } from './types';
import { WorkspaceCadConvert } from './WorkspaceCadConvert';

const HINT = 'p-[var(--s-5)] text-xs text-muted';

/**
 * Правая панель вкладки CAD: слои, замечания, масштаб, файлы (с результатом), трассы механики и
 * задание листа рабочей области.
 *
 * Раздел «Зоны» - разметка помещений и дверей листа - есть и у листа без задания.
 * Раздел «Конструкции» (кладка и монолит, ADR-0038) - у листа с видом.
 * Показано только задание открытого листа. Лист без задания получает кнопку «Преобразовать лист
 * в CAD», с идущим или упавшим заданием - только раздел «Задание» (у упавшего та же кнопка):
 * диагностики вида у него нет. Ширину и сворачивание панели ведёт каркас рабочей области.
 */
export const WorkspaceCadSide: FC<IWorkspaceCadSideProps> = ({
  state,
  sheetLabel,
  loadError,
  onRetry,
  job,
  convert,
  viewLoading,
  viewError,
  view,
  zones = null,
  constructions = null,
}) => {
  // Раздел живёт здесь: при переходе на другой лист панель остаётся на выбранном разделе.
  const [sideTab, setSideTab] = useState('layers');

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

  if (state === 'none' || job === null) {
    const none = (
      <div className="flex flex-col gap-[var(--s-3)] p-[var(--s-5)]" data-testid="workspace-cad-none">
        {sheetLabel !== null && (
          <p className="text-xs text-muted">
            Лист <span className="text-text">{sheetLabel}</span>
          </p>
        )}
        <p className="text-sm">Лист не преобразовывался</p>
        <p className="text-xs text-muted">Запустите преобразование: результат появится здесь.</p>
        {convert && <WorkspaceCadConvert key={convert.pageIndex} {...convert} />}
      </div>
    );
    // Зоны размечают и лист без задания: эталон для движка нужен до преобразования.
    if (zonesTab === null) return none;
    return (
      <CadSidePanel
        label="Панель CAD"
        tabs={[{ id: 'job', label: 'Задание', content: none }, zonesTab]}
        active={sideTab}
        onActiveChange={setSideTab}
      />
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
        {job.failed && convert && <WorkspaceCadConvert key={convert.pageIndex} {...convert} />}
      </div>
    ),
  };

  const tabs: readonly ICadSideTab[] = view
    ? [
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
          ? [{ id: 'mep', label: 'Трассы', content: <CadMepPanel {...view.mep} /> }]
          : []),
        ...(zonesTab ? [zonesTab] : []),
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
      ]
    : [...(zonesTab ? [zonesTab] : []), jobTab];

  return (
    <CadSidePanel label="Панель CAD" tabs={tabs} active={sideTab} onActiveChange={setSideTab} />
  );
};
