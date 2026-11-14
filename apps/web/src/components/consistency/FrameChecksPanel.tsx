'use client';

import type { FrameCheckOut } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { StatusBadge } from '@/components/ui';
import {
  CHECK_STATUS_LABELS,
  CHECK_STATUS_TONES,
  checkPlace,
  countChecks,
  groupChecks,
} from '@/lib/consistency/building-frame';

/**
 * Проверки комплектности и «ПЗ ↔ каркас» по подтверждённым данным. «Не проверено» — это не
 * «совпадает»: у таких строк своя причина. Ссылка ведёт на файл и страницу или ответ ПЗ.
 */

interface IPanelProps {
  readonly checks: readonly FrameCheckOut[];
}

export const FrameChecksPanel: FC<IPanelProps> = ({ checks }) => {
  const [onlyMismatches, setOnlyMismatches] = useState(true);
  const counts = countChecks(checks);
  const groups = groupChecks(checks, onlyMismatches);

  return (
    <section aria-labelledby="frame-checks" className="flex flex-col gap-[var(--s-4)]">
      <div className="flex flex-wrap items-center gap-[var(--s-4)]">
        <h2 id="frame-checks" className="text-base font-semibold">
          Проверки
        </h2>
        <StatusBadge tone="danger">Расхождений: {counts.mismatch}</StatusBadge>
        <StatusBadge tone="success">Совпадает: {counts.match}</StatusBadge>
        <StatusBadge tone="neutral">Не проверено: {counts.not_run}</StatusBadge>
        <label className="ml-auto flex cursor-pointer items-center gap-[var(--s-3)] text-sm max-sm:ml-0 max-md:min-h-[44px]">
          <input
            type="checkbox"
            checked={onlyMismatches}
            onChange={(event) => setOnlyMismatches(event.target.checked)}
            className="h-[16px] w-[16px] accent-[var(--accent)]"
          />
          Только расхождения
        </label>
      </div>
      {groups.length === 0 && (
        <p className="text-sm text-muted">
          {onlyMismatches ? 'Расхождений нет.' : 'Проверок нет.'}
        </p>
      )}
      {groups.map((group) => (
        <div
          key={group.code}
          className="rounded-[var(--radius-md)] border border-border bg-surface"
        >
          <h3 className="border-b border-border px-[var(--s-5)] py-[var(--s-3)] text-sm font-semibold">
            {group.title}
          </h3>
          <ul className="divide-y divide-border">
            {group.items.map((item, index) => (
              <li
                key={`${group.code}-${index}`}
                data-testid="frame-check"
                className="flex flex-col gap-[var(--s-2)] px-[var(--s-5)] py-[var(--s-3)]"
              >
                <div className="flex flex-wrap items-center gap-[var(--s-3)]">
                  <StatusBadge tone={CHECK_STATUS_TONES[item.status]}>
                    {CHECK_STATUS_LABELS[item.status]}
                  </StatusBadge>
                  {checkPlace(item) && (
                    <span className="text-xs text-muted">{checkPlace(item)}</span>
                  )}
                </div>
                <p className="text-sm [overflow-wrap:anywhere]">{item.message}</p>
                {item.refs.length > 0 && (
                  <ul className="flex flex-col gap-[var(--s-1)] text-xs text-muted">
                    {item.refs.map((ref) => (
                      <li key={`${ref.kind}-${ref.id}`} className="[overflow-wrap:anywhere]">
                        {ref.kind === 'answer'
                          ? 'Ответ ПЗ: '
                          : ref.kind === 'level'
                            ? 'Уровень: '
                            : ''}
                        {ref.label}
                        {ref.file_name !== null &&
                          ` — ${ref.file_name}${ref.page_index === null ? '' : `, стр. ${ref.page_index + 1}`}`}
                      </li>
                    ))}
                  </ul>
                )}
              </li>
            ))}
          </ul>
        </div>
      ))}
    </section>
  );
};
