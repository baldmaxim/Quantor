'use client';

import type { CadPipelineStageRead } from '@quantor/api-client';
import { useId, useState, type FC } from 'react';

import { CadPipelineStageErrorDetails } from './CadPipelineStageErrorDetails';

/** Причина отказа этапа одной строкой и кнопка «Подробнее»: сведения о задании грузятся по ней. */

export interface ICadPipelineStageErrorProps {
  readonly projectId: string;
  readonly revisionId: string;
  readonly stage: CadPipelineStageRead;
  /** Короткий текст отказа (код -> понятная фраза). */
  readonly text: string | null;
}

export const CadPipelineStageError: FC<ICadPipelineStageErrorProps> = ({
  projectId,
  revisionId,
  stage,
  text,
}) => {
  const [open, setOpen] = useState(false);
  const panelId = useId();

  return (
    <div className="flex min-w-0 flex-col items-start gap-[var(--s-2)]">
      <div className="flex flex-wrap items-center gap-x-[var(--s-4)]">
        {text && <p className="m-0 text-xs text-danger [overflow-wrap:anywhere]">{text}</p>}
        <button
          type="button"
          aria-expanded={open}
          aria-controls={panelId}
          onClick={() => setOpen((value) => !value)}
          className="inline-flex min-h-[44px] items-center text-xs text-accent underline underline-offset-4"
        >
          {open ? 'Скрыть' : 'Подробнее'}
        </button>
      </div>
      <div id={panelId} className="w-full min-w-0">
        {open && (
          <CadPipelineStageErrorDetails projectId={projectId} revisionId={revisionId} stage={stage} />
        )}
      </div>
    </div>
  );
};
