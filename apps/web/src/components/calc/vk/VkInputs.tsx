'use client';

import type { CalcPassportRead, CalcVkSystemReadinessRead } from '@quantor/api-client';

import { EmptyState, StatusBadge } from '@/components/ui';
import { SEMANTICS } from '@/lib/calc/vk';

/**
 * Исходные данные системы: что найдено автоматически и использовано, чего нет и что именно без
 * этого не определяется. Анкеты нет: человек работает только с недостающим.
 */

interface IVkInputsProps {
  system: CalcVkSystemReadinessRead | undefined;
  passport: CalcPassportRead | undefined;
}

export const VkInputs = ({ system, passport }: IVkInputsProps) => {
  if (!system) return <EmptyState compact title="Готовность не загрузилась" />;
  const used = passport?.body.used_facts ?? [];
  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      <p className="text-sm wrap-anywhere">
        Требований {system.inputs.total}: найдено автоматически {system.inputs.found_auto}, введено
        вручную {system.inputs.found_manual}, выводится {system.inputs.derivable}, нужен человек{' '}
        {system.inputs.needs_human}, не проверено {system.inputs.not_inspected}.{' '}
        <StatusBadge tone={SEMANTICS[system.semantics].tone}>
          {SEMANTICS[system.semantics].label}
        </StatusBadge>{' '}
        <span className="text-muted">{system.semantics_note}</span>
      </p>
      <section className="flex flex-col gap-[var(--s-2)]">
        <h3 className="text-sm font-medium">Не хватает — и что без этого не определяется</h3>
        {system.missing.length === 0 ? (
          <p className="text-sm text-muted">Всё нужное найдено или выводится.</p>
        ) : (
          <ul className="flex list-none flex-col gap-[var(--s-2)]">
            {system.missing.map((item) => {
              const blocks =
                passport?.body.missing.find((row) => row.requirement_id === item.requirement_id)
                  ?.blocks ?? item.blocks;
              return (
                <li
                  key={item.requirement_id}
                  className="flex flex-col gap-[var(--s-1)] rounded-[var(--radius-sm)] border border-border px-[var(--s-4)] py-[var(--s-3)] text-sm"
                >
                  <span className="font-medium wrap-anywhere">
                    {item.title}{' '}
                    <span className="text-xs text-muted">
                      {item.level} · {item.status}
                    </span>
                  </span>
                  {item.reason && <span className="text-muted wrap-anywhere">{item.reason}</span>}
                  {blocks.length > 0 && (
                    <span className="wrap-anywhere">Влияет на: {blocks.join(', ')}</span>
                  )}
                </li>
              );
            })}
          </ul>
        )}
      </section>
      {used.length > 0 && (
        <section className="flex flex-col gap-[var(--s-2)]">
          <h3 className="text-sm font-medium">Использовано в расчёте</h3>
          <ul className="flex list-none flex-col divide-y divide-border rounded-[var(--radius-sm)] border border-border text-sm">
            {used.map((fact) => (
              <li
                key={fact.fact_key}
                className="flex flex-wrap gap-x-[var(--s-4)] gap-y-[var(--s-1)] px-[var(--s-4)] py-[var(--s-2)]"
              >
                <span className="min-w-0 flex-1 wrap-anywhere">{fact.title}</span>
                <span className="font-mono">{fact.value}</span>
                <span className="text-xs text-muted">
                  {fact.source} · {fact.method}
                </span>
              </li>
            ))}
          </ul>
        </section>
      )}
    </div>
  );
};
