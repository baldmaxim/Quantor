import type { FC } from 'react';

import {
  MAIN_STEP_KEYS,
  type IPipelineStep,
  type PipelineStepKey,
  type PipelineStepState,
} from '@/lib/cad/pipeline';
import { PIPELINE_STATE_WORDS } from '@/lib/cad/pipeline-view';

/**
 * Дорожка конвейера листа: шесть основных шагов в ряд, соединённых линией. Заполненная часть
 * линии показывает ход обработки с одного взгляда. Состояние шага передано не только цветом:
 * форма значка, слово для чтения с экрана и подсказка. 3D DXF в дорожку не входит.
 */

export interface IPipelineStepperProps {
  readonly steps: readonly IPipelineStep[];
  readonly size?: 'md' | 'sm';
}

/** Шаги, где решение или действие за человеком. */
const HUMAN_STEPS: ReadonlySet<PipelineStepKey> = new Set(['calibration', 'approval', 'routes']);

const isFinished = (state: PipelineStepState): boolean => state === 'done' || state === 'skipped';

const NODE_BASE = 'relative z-10 flex flex-none items-center justify-center rounded-full';

const NODE_STYLES: Readonly<Record<PipelineStepState, string>> = {
  done: 'bg-success text-surface',
  running: 'border-2 border-accent-soft bg-surface text-accent',
  review: 'bg-warning text-surface',
  failed: 'bg-danger text-surface',
  todo: 'border-2 border-border-strong bg-surface',
  blocked: 'border-2 border-border-strong bg-surface opacity-50',
  skipped: 'border-2 border-dashed border-border-strong bg-surface text-muted',
};

const ICON_PROPS = {
  viewBox: '0 0 16 16',
  fill: 'none',
  stroke: 'currentColor',
  strokeWidth: 2,
  strokeLinecap: 'round',
  strokeLinejoin: 'round',
  'aria-hidden': true,
  className: 'size-3',
} as const;

const NodeIcon: FC<{ readonly state: PipelineStepState }> = ({ state }) => {
  switch (state) {
    case 'done':
      return (
        <svg {...ICON_PROPS}>
          <path d="M3.5 8.5l3 3 6-7" />
        </svg>
      );
    case 'review':
      return (
        <svg {...ICON_PROPS}>
          <path d="M8 3v6M8 12.5v.01" />
        </svg>
      );
    case 'failed':
      return (
        <svg {...ICON_PROPS}>
          <path d="M4 4l8 8M12 4l-8 8" />
        </svg>
      );
    case 'skipped':
      return (
        <svg {...ICON_PROPS}>
          <path d="M4.5 8h7" />
        </svg>
      );
    case 'running':
      return (
        <svg
          viewBox="0 0 16 16"
          fill="none"
          stroke="currentColor"
          strokeWidth={2}
          strokeLinecap="round"
          aria-hidden="true"
          className="absolute inset-0 size-full motion-safe:animate-spin"
        >
          <path d="M8 1.5a6.5 6.5 0 0 1 6.5 6.5" />
        </svg>
      );
    default:
      return null;
  }
};

const PersonIcon: FC = () => (
  <svg
    viewBox="0 0 16 16"
    fill="currentColor"
    aria-hidden="true"
    className="size-2.5 flex-none text-muted"
  >
    <circle cx="8" cy="5" r="3" />
    <path d="M2 14.5c0-3 2.7-5 6-5s6 2 6 5z" />
  </svg>
);

const progressOf = (step: IPipelineStep): string | null =>
  step.state === 'running' && step.detail !== null && step.detail.endsWith('%') ? step.detail : null;

const titleOf = (step: IPipelineStep): string =>
  `${step.label}: ${PIPELINE_STATE_WORDS[step.state]}${step.detail ? ` · ${step.detail}` : ''}`;

export const PipelineStepper: FC<IPipelineStepperProps> = ({ steps, size = 'md' }) => {
  const track = steps.filter((step) => (MAIN_STEP_KEYS as readonly PipelineStepKey[]).includes(step.key));
  const current = track.find((step) => !isFinished(step.state)) ?? null;
  const nodeSize = size === 'sm' ? 'size-5' : 'size-6';
  const rowHeight = size === 'sm' ? 'h-5' : 'h-6';

  return (
    <div className="@container w-full">
      <ol
        className="m-0 grid list-none grid-cols-6 gap-0 p-0"
        aria-label="Шаги конвейера"
      >
        {track.map((step, index) => {
          const previous = index > 0 ? track[index - 1] : null;
          const filled = previous !== null && previous !== undefined && isFinished(previous.state);
          const isCurrent = current !== null && current.key === step.key;
          const progress = progressOf(step);
          return (
            <li
              key={step.key}
              title={titleOf(step)}
              aria-current={isCurrent ? 'step' : undefined}
              className="relative flex min-w-0 flex-col items-center"
            >
              <div className={`relative flex w-full items-center justify-center ${rowHeight}`}>
                {previous && (
                  <span
                    aria-hidden="true"
                    className={`absolute top-1/2 right-1/2 h-0.5 w-full -translate-y-1/2 ${
                      filled ? 'bg-success' : 'bg-border'
                    }`}
                  />
                )}
                <span className={`${NODE_BASE} ${nodeSize} ${NODE_STYLES[step.state]}`}>
                  <NodeIcon state={step.state} />
                </span>
              </div>
              <span className="mt-1 flex max-w-full flex-col items-center text-center text-[11px] leading-tight @max-[399px]:sr-only">
                <span
                  className={`inline-flex max-w-full items-center justify-center gap-0.5 [overflow-wrap:anywhere] ${
                    isCurrent ? 'font-semibold text-text' : 'text-muted'
                  }`}
                >
                  {HUMAN_STEPS.has(step.key) && <PersonIcon />}
                  <span className="line-clamp-2">{step.label}</span>
                </span>
                {HUMAN_STEPS.has(step.key) && <span className="sr-only"> — действие человека</span>}
                {progress && <span className="text-muted">{progress}</span>}
              </span>
              <span className="sr-only">: {PIPELINE_STATE_WORDS[step.state]}</span>
            </li>
          );
        })}
      </ol>
      {current && (
        <p
          aria-hidden="true"
          className="m-0 mt-1 hidden text-center text-[11px] leading-tight font-semibold @max-[399px]:block"
        >
          {current.label}
          {current.detail ? <span className="font-normal text-muted"> · {current.detail}</span> : null}
        </p>
      )}
    </div>
  );
};
