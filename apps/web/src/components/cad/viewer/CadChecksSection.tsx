'use client';

import type { CadChecksRead, CadFrameRead } from '@quantor/api-client';
import type { FC } from 'react';

import { Field, InspectorSection, StatusBadge } from '@/components/ui';
import { formatBool, formatInt, formatNumber, NO_VALUE } from '@/lib/cad/view-format';

interface ICadChecksSectionProps {
  checks: CadChecksRead | null;
  frame: CadFrameRead;
}

const LIST = 'grid grid-cols-[minmax(0,1fr)_minmax(0,1.2fr)] gap-x-[var(--s-5)] gap-y-[var(--s-3)]';

export const CadChecksSection: FC<ICadChecksSectionProps> = ({ checks, frame }) => {
  const layers = checks ? Object.entries(checks.layers) : [];

  return (
    <>
      <InspectorSection
        title="Кадр координат"
        aside={
          <StatusBadge tone={frame.confirmed ? 'success' : 'warning'} dot={false}>
            {frame.confirmed ? 'подтверждён' : 'не подтверждён'}
          </StatusBadge>
        }
      >
        {frame.confirmed ? (
          <dl className={LIST}>
            <Field label="Единицы DXF">{frame.units ?? NO_VALUE}</Field>
            <Field label="Начало координат на странице, pt">
              {frame.origin_pt
                ? `${formatNumber(frame.origin_pt[0], 2)}; ${formatNumber(frame.origin_pt[1], 2)}`
                : NO_VALUE}
            </Field>
            <Field label="мм на точку PDF">{formatNumber(frame.mm_per_pdf_point, 6)}</Field>
          </dl>
        ) : (
          <p className="text-xs [overflow-wrap:anywhere]">
            {frame.reason ?? 'Причина не указана.'}
          </p>
        )}
      </InspectorSection>

      <InspectorSection title="Проверки DXF">
        {!checks ? (
          <p className="text-xs text-muted">Проверок DXF нет: файл в этой попытке не выпускался.</p>
        ) : (
          <div className="flex min-w-0 flex-col gap-[var(--s-5)]">
            <dl className={LIST}>
              <Field label="Ошибок аудита DXF">{formatInt(checks.audit_errors)}</Field>
              <Field label="Вставок блоков дверей">{formatInt(checks.door_block_inserts)}</Field>
              <Field label="Вставок блоков ворот">{formatInt(checks.gate_block_inserts)}</Field>
              <Field label="Заливок в источнике">{formatInt(checks.source_fill_count)}</Field>
              <Field label="Распознано монолитных заливок">
                {formatInt(checks.recognized_monolith_fill_count)}
              </Field>
              <Field label="Блоков дверей">{formatInt(checks.door_block_count)}</Field>
              <Field label="Строк ведомости помещений">{formatInt(checks.rooms_schedule_rows)}</Field>
              <Field label="Распознано строк помещений">{formatInt(checks.rooms_recognized_rows)}</Field>
              <Field label="Область плана одобрена">{formatBool(checks.region_approved)}</Field>
              <Field label="Все заливки валидны">{formatBool(checks.all_source_fills_valid)}</Field>
              <Field label="Выпуск количеств разрешён">
                {formatBool(checks.quantity_release_allowed)}
              </Field>
            </dl>

            {layers.length > 0 && (
              <div className="flex flex-col gap-[var(--s-3)]">
                <p className="text-xs text-muted">Слои DXF</p>
                <ul className="flex flex-wrap gap-[var(--s-3)]">
                  {layers.map(([name, count]) => (
                    <li
                      key={name}
                      className="mono rounded-[var(--radius-sm)] border border-border bg-surface-muted px-[var(--s-4)] py-[var(--s-2)] text-xs [overflow-wrap:anywhere]"
                    >
                      {name}: {formatInt(count)}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          </div>
        )}
      </InspectorSection>
    </>
  );
};
