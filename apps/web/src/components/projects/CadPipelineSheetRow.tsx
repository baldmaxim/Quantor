import type { CadPipelineSheetRead } from '@quantor/api-client';
import { useId, useState, type FC } from 'react';

import { PipelineStepper } from '@/components/cad/pipeline/PipelineStepper';
import { type BadgeTone, ButtonLink, cx, StatusBadge } from '@/components/ui';
import { IconChevronRight } from '@/components/ui/icons';
import { formatFloorTitle, formatFloorTitleFull } from '@/lib/cad/floor-title';
import {
  sheetProgress,
  sheetSteps,
  sheetSummary,
  sheetUpdateBadge,
  type PipelineStepState,
} from '@/lib/cad/pipeline';
import { workspaceCadHref } from '@/lib/cad/workspace-url';

import { CadPipelineSheetControls } from './CadPipelineSheetControls';

/**
 * Лист в панели «Обработка»: итог одной строкой, дорожка шагов конвейера и переход в рабочую
 * область на вкладку CAD. Нажатие на шапку раскрывает управление шагами (запуск, повтор, причина
 * отказа). Необязательный 3D DXF в дорожку не входит и показан отдельной меткой. Слева -
 * чекбокс выбора для массового запуска: отдельная тап-цель, строку не раскрывает.
 */

export interface ICadPipelineSheetRowProps {
  readonly projectId: string;
  readonly revisionId: string;
  readonly sheet: CadPipelineSheetRead;
  /** Позиция листа в рабочей области (с 1). */
  readonly position: number;
  /** Лист выбран для массового запуска. */
  readonly selected: boolean;
  /** Лист доступен массовому запуску; иначе чекбокс неактивен. */
  readonly selectable: boolean;
  readonly onSelectedChange: (checked: boolean) => void;
}

const FLOOR3D_BADGES: Partial<Record<PipelineStepState, { tone: BadgeTone; label: string }>> = {
  queued: { tone: 'accent', label: '3D DXF: в очереди' },
  running: { tone: 'accent', label: '3D DXF…' },
  done: { tone: 'success', label: '3D DXF готов' },
  failed: { tone: 'danger', label: '3D DXF: ошибка' },
};

export const CadPipelineSheetRow: FC<ICadPipelineSheetRowProps> = ({
  projectId,
  revisionId,
  sheet,
  position,
  selected,
  selectable,
  onSelectedChange,
}) => {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  const steps = sheetSteps(sheet);
  const summary = sheetSummary(sheet);
  const progress = sheetProgress(sheet);
  const updateBadge = sheetUpdateBadge(sheet);
  const failed = steps.find((step) => step.state === 'failed' && step.key !== 'floor3d');
  const floor3d = steps.find((step) => step.key === 'floor3d');
  const floor3dBadge = floor3d ? FLOOR3D_BADGES[floor3d.state] : undefined;
  const sheetName = `Лист ${sheet.page_label ?? sheet.page_index + 1}`;
  // Главное - этаж по заголовку плана или наименование листа; номер листа - серой подписью ниже.
  const floorTitle = formatFloorTitle(sheet.floor_title, '');
  const name = floorTitle || sheet.title || sheetName;
  const subtitle =
    name === sheetName ? null : [sheetName, floorTitle && sheet.title].filter(Boolean).join(' · ');

  const toggle = () => setOpen((value) => !value);

  const href = workspaceCadHref(projectId, {
    revision: revisionId,
    position,
    job: sheet.convert?.job_id ?? null,
    view: null,
  });

  return (
    <li className="flex flex-col gap-[var(--s-3)] border-b border-border py-[var(--s-4)] last:border-b-0">
      <div className="flex items-center gap-[var(--s-4)]">
        <label className="flex size-[44px] flex-none cursor-pointer items-center justify-center">
          <input
            type="checkbox"
            aria-label={`Выбрать лист ${sheet.page_label ?? sheet.page_index + 1}`}
            checked={selected}
            disabled={!selectable}
            onChange={(event) => onSelectedChange(event.target.checked)}
            className="size-5 accent-accent"
          />
        </label>
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={toggle}
          className="flex min-h-[44px] min-w-0 flex-1 items-center gap-[var(--s-3)] text-left"
        >
          <IconChevronRight
            className={cx(
              'flex-none text-muted transition-transform duration-150 motion-reduce:transition-none',
              open && 'rotate-90',
            )}
          />
          <span className="flex min-w-0 flex-1 flex-wrap items-center gap-x-[var(--s-4)] gap-y-[var(--s-2)]">
            <span className="flex min-w-0 flex-col">
              <span
                className="text-sm font-medium [overflow-wrap:anywhere]"
                title={formatFloorTitleFull(sheet.floor_title) ?? undefined}
              >
                {name}
              </span>
              {subtitle && (
                <span className="text-xs text-muted [overflow-wrap:anywhere]">{subtitle}</span>
              )}
            </span>
            {sheet.scale_source === 'auto' && (
              <StatusBadge tone="neutral" dot={false}>
                Масштаб: авто
              </StatusBadge>
            )}
            <StatusBadge tone={summary.tone} wrap>
              {summary.label}
            </StatusBadge>
            {updateBadge && (
              <span title={updateBadge.hint}>
                <StatusBadge tone={updateBadge.tone} wrap>
                  {updateBadge.label}
                </StatusBadge>
              </span>
            )}
            <span
              className="font-mono text-xs text-muted"
              title="Завершено основных шагов конвейера"
            >
              {`${progress.done} из ${progress.total}`}
            </span>
          </span>
        </button>
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

      {/* Щелчок по дорожке тоже раскрывает лист; с клавиатуры - кнопка шапки. */}
      <div onClick={toggle}>
        <PipelineStepper steps={steps} />
      </div>

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

      <div id={panelId}>
        {open && (
          <CadPipelineSheetControls
            projectId={projectId}
            revisionId={revisionId}
            sheet={sheet}
            position={position}
          />
        )}
      </div>
    </li>
  );
};
