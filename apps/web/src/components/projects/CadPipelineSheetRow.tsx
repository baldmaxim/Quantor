import type { CadPipelineSheetRead } from '@quantor/api-client';
import type { FC } from 'react';

import { PipelineStepper } from '@/components/cad/pipeline/PipelineStepper';
import { type BadgeTone, ButtonLink, StatusBadge } from '@/components/ui';
import { formatFloorTitle, formatFloorTitleFull } from '@/lib/cad/floor-title';
import {
  sheetProgress,
  sheetSteps,
  sheetSummary,
  type PipelineStepState,
} from '@/lib/cad/pipeline';
import { workspaceCadHref } from '@/lib/cad/workspace-url';

/**
 * Лист в панели «Обработка»: итог одной строкой, дорожка шагов конвейера и переход в рабочую
 * область на вкладку CAD. Необязательный 3D DXF в дорожку не входит и показан отдельной меткой.
 */

export interface ICadPipelineSheetRowProps {
  readonly projectId: string;
  readonly revisionId: string;
  readonly sheet: CadPipelineSheetRead;
  /** Позиция листа в рабочей области (с 1). */
  readonly position: number;
}

const FLOOR3D_BADGES: Partial<Record<PipelineStepState, { tone: BadgeTone; label: string }>> = {
  running: { tone: 'accent', label: '3D DXF…' },
  done: { tone: 'success', label: '3D DXF готов' },
  failed: { tone: 'danger', label: '3D DXF: ошибка' },
};

export const CadPipelineSheetRow: FC<ICadPipelineSheetRowProps> = ({
  projectId,
  revisionId,
  sheet,
  position,
}) => {
  const steps = sheetSteps(sheet);
  const summary = sheetSummary(sheet);
  const progress = sheetProgress(sheet);
  const failed = steps.find((step) => step.state === 'failed' && step.key !== 'floor3d');
  const floor3d = steps.find((step) => step.key === 'floor3d');
  const floor3dBadge = floor3d ? FLOOR3D_BADGES[floor3d.state] : undefined;
  const sheetName = `Лист ${sheet.page_label ?? sheet.page_index + 1}`;
  // Лист называется этажом по заголовку плана; номер листа - второй серой подписью.
  const floorTitle = formatFloorTitle(sheet.floor_title, '');
  const name = floorTitle || sheetName;

  const href = workspaceCadHref(projectId, {
    revision: revisionId,
    position,
    job: sheet.convert?.job_id ?? null,
    view: null,
  });

  return (
    <li className="flex flex-col gap-[var(--s-3)] border-b border-border py-[var(--s-4)] last:border-b-0">
      <div className="flex items-center gap-[var(--s-4)]">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-x-[var(--s-4)] gap-y-[var(--s-2)]">
          <span
            className="text-sm font-medium [overflow-wrap:anywhere]"
            title={formatFloorTitleFull(sheet.floor_title) ?? undefined}
          >
            {name}
          </span>
          {floorTitle && <span className="text-xs text-muted">{sheetName}</span>}
          <StatusBadge tone={summary.tone} wrap>
            {summary.label}
          </StatusBadge>
          <span
            className="font-mono text-xs text-muted"
            title="Завершено основных шагов конвейера"
          >
            {`${progress.done} из ${progress.total}`}
          </span>
        </div>
        <ButtonLink
          href={href}
          compact
          aria-label={`Открыть ${name} в CAD`}
          transitionTypes={['nav-forward']}
          className="flex-none"
        >
          Открыть
        </ButtonLink>
      </div>

      <PipelineStepper steps={steps} />

      {(failed?.detail || floor3dBadge) && (
        <div className="flex flex-wrap items-center gap-x-[var(--s-4)] gap-y-[var(--s-2)]">
          {failed?.detail && <p className="m-0 text-xs text-danger">{failed.detail}</p>}
          {floor3dBadge && (
            <StatusBadge tone={floor3dBadge.tone} dot={false}>
              {floor3dBadge.label}
            </StatusBadge>
          )}
        </div>
      )}
    </li>
  );
};
