'use client';

import type { CadViewDiagnosticsRead } from '@quantor/api-client';
import type { FC } from 'react';

import { StatusBadge } from '@/components/ui';
import { resultInfo, stateLabel, stateTone } from '@/lib/cad/stages';

interface ICadViewHeaderProps {
  diagnostics: CadViewDiagnosticsRead;
}

/**
 * Что именно выпущено, словами. Три исхода не смешиваются: DXF с проверкой, диагностика без DXF
 * и ошибка вида - у каждого свой смысл для инженера.
 */
const outcomeNote = (diagnostics: CadViewDiagnosticsRead): string | null => {
  if (diagnostics.status === 'error') {
    return 'Вид завершился ошибкой: DXF не выпущен, данные ниже - то, что успел записать движок.';
  }
  if (diagnostics.result_status === 'completed_requires_review') {
    return 'DXF выпущен как кандидат движка. До проверки инженером в работу не идёт.';
  }
  if (diagnostics.result_status === 'no_cad_review_required') {
    return 'DXF не создан: масштаб не подтверждён размерной проверкой, выпущена только диагностика.';
  }
  return null;
};

export const CadViewHeader: FC<ICadViewHeaderProps> = ({ diagnostics }) => {
  const info = resultInfo(diagnostics.result_status);
  const note = outcomeNote(diagnostics);
  const pageDiffers = diagnostics.legacy_pdf_page !== diagnostics.page_index + 1;

  return (
    <header className="flex min-w-0 flex-col gap-[var(--s-4)]">
      <div className="flex flex-wrap items-baseline gap-x-[var(--s-5)] gap-y-[var(--s-2)]">
        <h3 className="text-md font-medium">
          Стр. {diagnostics.legacy_pdf_page} · вид {diagnostics.view}
        </h3>
        {pageDiffers && (
          <span className="text-xs text-muted">индекс страницы: {diagnostics.page_index + 1}</span>
        )}
        <span className="text-xs text-muted">попытка {diagnostics.attempt}</span>
      </div>

      <div className="flex flex-wrap items-center gap-[var(--s-3)]">
        <StatusBadge tone={stateTone(diagnostics.status)}>
          Вид: {stateLabel(diagnostics.status)}
        </StatusBadge>
        <StatusBadge tone="neutral" dot={false} wrap>
          Масштаб: {diagnostics.scale_status ?? '—'}
        </StatusBadge>
        {info && (
          <StatusBadge tone={info.tone} dot={false} wrap>
            {info.label}
          </StatusBadge>
        )}
      </div>

      {note && <p className="text-xs [overflow-wrap:anywhere]">{note}</p>}

      {/* QA-контур приёмку не выполняет никогда: это отдельный шаг человека. */}
      <p
        className="rounded-[var(--radius-sm)] border border-warning-soft bg-warning-soft px-[var(--s-4)] py-[var(--s-3)] text-xs font-medium text-warning"
        data-testid="cad-acceptance"
      >
        Инженерная приёмка: не выполнена
      </p>
    </header>
  );
};
