'use client';

import type { FC } from 'react';

import { useCadFinishSheet, useCadFinishTemplates } from '@/lib/cad/finishes-queries';
import { buildFinishSteps } from '@/lib/cad/finish-steps';
import { FINISH_WARNING_LABELS } from '@/lib/cad/room-types';

import { CadFinishSheet } from './CadFinishSheet';
import { CadFinishStep, type ICadFinishStepAction } from './CadFinishStep';
import { CadFinishTemplates } from './CadFinishTemplates';
import { CadFinishZoneLinks } from './CadFinishZoneLinks';

export interface ICadFinishPanelProps {
  projectId: string;
  revisionId: string | null;
  /** Индекс страницы открытого листа; `null` - лист не выбран. */
  pageIndex: number | null;
  /** Флаг `cad.export` включён и вкладка CAD открывалась: без него запросов нет. */
  load: boolean;
  /** Выбранная на листе зона: подсвечивается в ведомости. */
  activeId: string | null;
  /** Выделить зону на листе (то же, что выбор в списке зон). */
  onActivate: (id: string | null) => void;
  /** Открыть соседний раздел панели: шаги отделки ведут в «Зоны» и «Конструкции». */
  onOpenTab?: (id: 'zones' | 'constructions') => void;
}

/**
 * Раздел «Отделка» правой панели CAD (ADR-0042): чек-лист из четырёх шагов - зоны с типом,
 * шаблоны проекта, шаблон у каждой зоны, ведомость листа. Все шаги видны сразу, это не мастер.
 */
export const CadFinishPanel: FC<ICadFinishPanelProps> = ({
  projectId,
  revisionId,
  pageIndex,
  load,
  activeId,
  onActivate,
  onOpenTab,
}) => {
  // Те же запросы, что в списке шаблонов и в ведомости: кеш общий, лишних обращений нет.
  const templates = useCadFinishTemplates(projectId, load);
  const sheet = useCadFinishSheet(projectId, revisionId, pageIndex, load);
  const steps = buildFinishSteps(sheet.data, templates.data);
  const zones = sheet.data?.zones ?? [];

  const openZones: ICadFinishStepAction | null =
    onOpenTab === undefined ? null : { label: 'Открыть «Зоны»', onClick: () => onOpenTab('zones') };

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-4)]" data-testid="cad-finish-panel">
      {steps.calibration !== null && (
        <div
          role="alert"
          className="flex min-w-0 flex-col gap-[var(--s-1)] rounded-[var(--radius-sm)] border border-warning-soft bg-warning-soft px-[var(--s-4)] py-[var(--s-3)]"
        >
          <span className="text-xs font-medium break-words text-warning">
            {FINISH_WARNING_LABELS.calibration_missing}
            {steps.calibration.zone_ids.length > 0 &&
              ` (зон: ${steps.calibration.zone_ids.length})`}
          </span>
          <CadFinishZoneLinks
            zoneIds={steps.calibration.zone_ids}
            zones={zones}
            onActivate={onActivate}
          />
        </div>
      )}

      <CadFinishStep
        number={1}
        title="Зоны и типы помещений"
        status={steps.zones.status}
        summary={steps.zones.summary}
        hint={steps.zones.hint}
        action={openZones}
      >
        <CadFinishZoneLinks
          zoneIds={steps.zones.untypedIds}
          zones={zones}
          onActivate={onActivate}
        />
      </CadFinishStep>

      <CadFinishStep
        number={2}
        title="Шаблоны отделки проекта"
        status={steps.templates.status}
        summary={steps.templates.summary}
        hint={steps.templates.hint}
      >
        <CadFinishTemplates
          projectId={projectId}
          load={load}
          collapsible={steps.templates.collapsed}
        />
      </CadFinishStep>

      <CadFinishStep
        number={3}
        title="Шаблон у каждой зоны"
        status={steps.assignment.status}
        summary={steps.assignment.summary}
        hint={steps.assignment.hint}
        action={openZones}
      >
        <CadFinishZoneLinks
          zoneIds={steps.assignment.withoutTemplateIds}
          zones={zones}
          onActivate={onActivate}
        />
      </CadFinishStep>

      <CadFinishStep
        number={4}
        title="Ведомость листа"
        status={steps.sheet.status}
        summary={steps.sheet.summary}
        hint={steps.sheet.hint}
      >
        <CadFinishSheet
          projectId={projectId}
          revisionId={revisionId}
          pageIndex={pageIndex}
          load={load}
          templates={templates.data ?? []}
          activeId={activeId}
          onActivate={onActivate}
          warnings={steps.sheet.warnings}
          onOpenConstructions={
            onOpenTab === undefined ? undefined : () => onOpenTab('constructions')
          }
        />
      </CadFinishStep>
    </div>
  );
};
