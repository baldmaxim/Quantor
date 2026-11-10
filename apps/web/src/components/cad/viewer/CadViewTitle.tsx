'use client';

import type { CadViewDiagnosticsRead } from '@quantor/api-client';
import type { FC } from 'react';

import { StatusBadge } from '@/components/ui';
import { resultInfo, stateLabel, stateTone } from '@/lib/cad/stages';

interface ICadViewTitleProps {
  diagnostics: CadViewDiagnosticsRead;
}

/** Компактный заголовок над холстом: страница, вид и один бейдж итога. Подробности - в панели. */
export const CadViewTitle: FC<ICadViewTitleProps> = ({ diagnostics }) => {
  const info = resultInfo(diagnostics.result_status);

  return (
    <div className="flex min-w-0 flex-wrap items-center gap-x-[var(--s-4)] gap-y-[var(--s-2)]">
      <h3 className="text-md font-medium whitespace-nowrap">
        Стр. {diagnostics.legacy_pdf_page} · вид {diagnostics.view}
      </h3>
      {info ? (
        <StatusBadge tone={info.tone} dot={false}>
          {info.label}
        </StatusBadge>
      ) : (
        <StatusBadge tone={stateTone(diagnostics.status)}>
          Вид: {stateLabel(diagnostics.status)}
        </StatusBadge>
      )}
    </div>
  );
};
