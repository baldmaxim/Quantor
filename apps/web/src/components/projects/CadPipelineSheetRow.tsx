import type { CadPipelineSheetRead } from '@quantor/api-client';
import type { FC } from 'react';

import { ButtonLink, StatusBadge } from '@/components/ui';
import { sheetSteps, sheetSummary } from '@/lib/cad/pipeline';
import {
  PIPELINE_STATE_GLYPHS as STATE_GLYPHS,
  PIPELINE_STATE_TONES as STATE_TONES,
  PIPELINE_STATE_WORDS as STATE_WORDS,
} from '@/lib/cad/pipeline-view';
import { workspaceCadHref } from '@/lib/cad/workspace-url';

/**
 * Лист в панели «Обработка»: шаги конвейера чипами, итог одной строкой и переход в рабочую
 * область на вкладку CAD. Состояние шага передано не только цветом: значок и слово для чтения
 * с экрана.
 */

export interface ICadPipelineSheetRowProps {
  readonly projectId: string;
  readonly revisionId: string;
  readonly sheet: CadPipelineSheetRead;
  /** Позиция листа в рабочей области (с 1). */
  readonly position: number;
}

export const CadPipelineSheetRow: FC<ICadPipelineSheetRowProps> = ({
  projectId,
  revisionId,
  sheet,
  position,
}) => {
  const steps = sheetSteps(sheet);
  const summary = sheetSummary(sheet);
  const failed = steps.find((step) => step.state === 'failed');
  const name = `Лист ${sheet.page_label ?? sheet.page_index + 1}`;

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
          <span className="text-sm font-medium [overflow-wrap:anywhere]">{name}</span>
          <StatusBadge tone={summary.tone} wrap>
            {summary.label}
          </StatusBadge>
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

      <ul className="m-0 flex list-none flex-wrap gap-[var(--s-2)] p-0" aria-label="Шаги">
        {steps.map((step) => (
          <li key={step.key}>
            <StatusBadge tone={STATE_TONES[step.state]} dot={false}>
              <span aria-hidden="true">{STATE_GLYPHS[step.state]}</span>
              {step.label}
              {step.detail && step.state !== 'failed' && (
                <span className="text-muted">· {step.detail}</span>
              )}
              <span className="sr-only">: {STATE_WORDS[step.state]}</span>
            </StatusBadge>
          </li>
        ))}
      </ul>

      {failed?.detail && <p className="text-xs text-danger">{failed.detail}</p>}
    </li>
  );
};
