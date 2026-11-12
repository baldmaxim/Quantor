'use client';

import type { CadPipelineSheetRead } from '@quantor/api-client';
import type { FC } from 'react';

import { Button, Skeleton } from '@/components/ui';
import { formatFloorTitle, formatFloorTitleFull } from '@/lib/cad/floor-title';
import type { IPipelineStep, PipelineStepKey } from '@/lib/cad/pipeline';
import {
  PIPELINE_STATE_GLYPHS,
  PIPELINE_STATE_TONES,
  PIPELINE_STATE_WORDS,
} from '@/lib/cad/pipeline-view';
import { queuePositionText } from '@/lib/cad/queue-view';

import type { IWorkspaceCadConvert } from './types';
import type { IWorkspaceCadPipeline } from './useWorkspaceCadPipeline';
import { WorkspaceCadConvert } from './WorkspaceCadConvert';
import { WorkspaceCadWallsRetry } from './WorkspaceCadWallsRetry';

/** Разделы правой панели, в которые ведут действия шагов. */
export const PIPELINE_PANEL_CONSTRUCTIONS = 'constructions';
export const PIPELINE_PANEL_MEP = 'mep';

/** Разделы правой панели, в которые ведут действия шагов и которые в панели сейчас есть. */
export const openablePanels = (
  hasView: boolean,
  hasMep: boolean,
  hasConstructions: boolean,
): string[] => [
  ...(hasView && hasMep ? [PIPELINE_PANEL_MEP] : []),
  ...(hasView && hasConstructions ? [PIPELINE_PANEL_CONSTRUCTIONS] : []),
];

export interface IWorkspaceCadPipelineProps {
  readonly pipeline: IWorkspaceCadPipeline;
  /** Запуск преобразования листа (единственное место запуска); `null` - лист не выбран. */
  readonly convert: IWorkspaceCadConvert | null;
  /** Разделы панели, которые сейчас есть: действие в отсутствующий раздел не показывается. */
  readonly openablePanels: readonly string[];
  readonly onOpenPanel: (id: string) => void;
}

const TONE_TEXT: Readonly<Record<string, string>> = {
  neutral: 'text-muted',
  accent: 'text-accent',
  success: 'text-success',
  warning: 'text-warning',
  danger: 'text-danger',
};

const HINT =
  'Конструкции и зоны считаются сами после преобразования. Зоны и трассы — кандидаты: проверьте и одобрите вид.';

const ACTIONABLE = new Set(['todo', 'failed', 'review']);

/** Первый шаг, ждущий действия: по нему показывается единственное основное действие. */
const nextStep = (steps: readonly IPipelineStep[]): IPipelineStep | null =>
  steps.find((step) => ACTIONABLE.has(step.state)) ?? null;

const BUTTON = 'self-start max-md:h-[44px]';

/** Виды листа с DXF, у которых последнее задание расчёта конструкций упало. */
const failedWallsViews = (sheet: CadPipelineSheetRead | null): number[] =>
  (sheet?.views ?? [])
    .filter((view) => {
      const walls = view.walls;
      if (!view.has_dxf || walls === null) return false;
      if (walls.status === 'queued' || walls.status === 'running') return false;
      return walls.status !== 'succeeded' || walls.result_status === 'failed';
    })
    .map((view) => view.view);

/**
 * Содержимое окна «Обработка листа» у бейджа в шапке: шаги конвейера открытого листа и одно
 * следующее действие. Запуск преобразования и калибровка живут только здесь (`WorkspaceCadConvert`).
 */
export const WorkspaceCadPipeline: FC<IWorkspaceCadPipelineProps> = ({
  pipeline,
  convert,
  openablePanels,
  onOpenPanel,
}) => {
  const {
    steps,
    sheet,
    isPending,
    isError,
    refetch,
    startAutoZones,
    startingZones,
    zonesError,
    queueAhead,
  } = pipeline;
  const convertNode = convert ? <WorkspaceCadConvert key={convert.pageIndex} {...convert} /> : null;

  if (isPending) {
    return (
      <div role="status" aria-label="Загрузка обработки листа" className="flex flex-col gap-[var(--s-3)]">
        <Skeleton className="h-[20px] w-[60%]" />
        <Skeleton className="h-[16px] w-[80%]" />
        <Skeleton className="h-[16px] w-[70%]" />
      </div>
    );
  }

  if (isError) {
    return (
      <div className="flex flex-col gap-[var(--s-4)]" data-testid="workspace-cad-pipeline">
        <p role="alert" className="text-xs text-danger">
          Не удалось загрузить состояние обработки листа.
        </p>
        <Button compact onClick={refetch} className={BUTTON}>
          Повторить
        </Button>
        {convertNode}
      </div>
    );
  }

  const next = nextStep(steps);
  const canOpen = (id: string) => openablePanels.includes(id);

  const action = (key: PipelineStepKey, state: IPipelineStep['state']) => {
    // Лист уже преобразован: повторный запуск (после обновления движка) - вторичное действие.
    if (key === 'convert' && state === 'done' && next?.key !== 'convert' && convert) {
      return (
        <WorkspaceCadConvert
          key={convert.pageIndex}
          {...convert}
          again
          currentJobId={sheet?.convert?.job_id ?? null}
        />
      );
    }
    if (next?.key !== key) return null;
    if (key === 'calibration' || key === 'convert') return convertNode;
    if (key === 'walls' && state === 'failed') {
      const jobId = sheet?.convert?.job_id;
      const failedViews = failedWallsViews(sheet);
      const showRetry = convert !== null && jobId !== undefined && failedViews.length > 0;
      if (!showRetry && !canOpen(PIPELINE_PANEL_CONSTRUCTIONS)) return null;
      return (
        <div className="flex min-w-0 flex-col items-start gap-[var(--s-3)]">
          {showRetry && (
            <WorkspaceCadWallsRetry
              key={`${jobId}:${failedViews.join(',')}`}
              projectId={convert.projectId}
              revisionId={convert.revisionId}
              jobId={jobId}
              pageIndex={convert.pageIndex}
              views={failedViews}
            />
          )}
          {canOpen(PIPELINE_PANEL_CONSTRUCTIONS) && (
            <Button compact onClick={() => onOpenPanel(PIPELINE_PANEL_CONSTRUCTIONS)} className={BUTTON}>
              Открыть Конструкции
            </Button>
          )}
        </div>
      );
    }
    const view = sheet?.views.find((row) => row.has_dxf);
    if (key === 'zones' && (state === 'failed' || (state === 'todo' && (view?.zones_count ?? 0) === 0))) {
      return (
        <div className="flex flex-col gap-[var(--s-2)]">
          <Button
            variant="primary"
            compact
            loading={startingZones}
            onClick={() => void startAutoZones()}
            className={BUTTON}
          >
            Разметить зоны автоматически
          </Button>
          {zonesError && (
            <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
              {zonesError}
            </p>
          )}
        </div>
      );
    }
    if (key === 'approval' && state === 'review' && canOpen(PIPELINE_PANEL_MEP)) {
      return (
        <Button variant="primary" compact onClick={() => onOpenPanel(PIPELINE_PANEL_MEP)} className={BUTTON}>
          Перейти к одобрению
        </Button>
      );
    }
    if (key === 'routes' && state === 'review' && canOpen(PIPELINE_PANEL_MEP)) {
      return (
        <Button variant="primary" compact onClick={() => onOpenPanel(PIPELINE_PANEL_MEP)} className={BUTTON}>
          Проверить трассы
        </Button>
      );
    }
    return null;
  };

  const floorTitle = formatFloorTitle(sheet?.floor_title, '');

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-5)]" data-testid="workspace-cad-pipeline">
      {floorTitle !== '' && (
        <p
          data-testid="pipeline-floor-title"
          title={formatFloorTitleFull(sheet?.floor_title) ?? undefined}
          className="m-0 text-sm font-semibold [overflow-wrap:anywhere]"
        >
          {floorTitle}
          <span className="ml-[var(--s-3)] text-xs font-normal text-muted">
            Лист {sheet?.page_label ?? (sheet ? sheet.page_index + 1 : '')}
          </span>
        </p>
      )}
      <ol className="m-0 flex list-none flex-col gap-[var(--s-4)] p-0" aria-label="Шаги обработки листа">
        {steps.map((step) => {
          const tone = TONE_TEXT[PIPELINE_STATE_TONES[step.state]] ?? 'text-muted';
          const extra = action(step.key, step.state);
          const position =
            step.state === 'queued' && step.jobId !== null
              ? queuePositionText(queueAhead.get(step.jobId))
              : null;
          return (
            <li key={step.key} className="flex min-w-0 flex-col gap-[var(--s-2)]">
              <div className="flex min-w-0 flex-wrap items-baseline gap-x-[var(--s-3)]">
                <span aria-hidden="true" className={`w-[1.25em] flex-none text-center ${tone}`}>
                  {PIPELINE_STATE_GLYPHS[step.state]}
                </span>
                <span className="text-sm font-medium">{step.label}</span>
                <span className={`text-xs ${tone}`}>{PIPELINE_STATE_WORDS[step.state]}</span>
              </div>
              {position && (
                <p
                  data-testid="pipeline-queue-position"
                  className="m-0 pl-[calc(1.25em+var(--s-3))] text-xs text-muted"
                >
                  {position}
                </p>
              )}
              {step.detail && (
                <p className={`m-0 pl-[calc(1.25em+var(--s-3))] text-xs [overflow-wrap:anywhere] ${
                  step.state === 'failed' ? 'text-danger' : 'text-muted'
                }`}>
                  {step.detail}
                </p>
              )}
              {extra && <div className="pl-[calc(1.25em+var(--s-3))]">{extra}</div>}
            </li>
          );
        })}
      </ol>
      <p className="text-xs text-muted">{HINT}</p>
    </div>
  );
};
