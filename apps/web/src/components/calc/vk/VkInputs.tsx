'use client';

import type { CalcPassportRead, CalcVkSystemReadinessRead } from '@quantor/api-client';
import Link from 'next/link';

import { EmptyState, StatusBadge } from '@/components/ui';
import { LEVEL_TITLES, READINESS_STATUS } from '@/lib/calc/format';
import { SEMANTICS } from '@/lib/calc/vk';

/**
 * Исходные данные системы: что найдено автоматически и использовано, чего нет и что именно без
 * этого не определяется. Анкеты нет: человек работает только с недостающим — вводит значение,
 * подтверждает назначение системы или решает расхождение на экране «Исходные данные».
 */

interface IVkInputsProps {
  projectId: string;
  system: CalcVkSystemReadinessRead | undefined;
  passport: CalcPassportRead | undefined;
}

export const VkInputs = ({ projectId, system, passport }: IVkInputsProps) => {
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
        <div className="flex flex-wrap items-baseline justify-between gap-[var(--s-3)]">
          <h3 className="text-sm font-medium">Не хватает — и что без этого не определяется</h3>
          <Link
            href={`/projects/${projectId}/calc`}
            className="inline-flex min-h-[44px] items-center text-sm text-accent underline-offset-2 hover:underline md:min-h-0"
          >
            Ввести или решить в «Исходных данных»
          </Link>
        </div>
        {system.missing.length === 0 ? (
          <p className="text-sm text-muted">Всё нужное найдено или выводится.</p>
        ) : (
          <ul className="flex list-none flex-col gap-[var(--s-2)]">
            {system.missing.map((item) => {
              const known = passport?.body.missing.find(
                (row) => row.requirement_id === item.requirement_id,
              );
              const blocks = known?.blocks ?? item.blocks;
              const notBlocks = known?.not_blocks ?? item.not_blocks;
              return (
                <li
                  key={item.requirement_id}
                  className="flex flex-col gap-[var(--s-1)] rounded-[var(--radius-sm)] border border-border px-[var(--s-4)] py-[var(--s-3)] text-sm"
                >
                  <span className="font-medium wrap-anywhere">
                    {item.title}{' '}
                    <span className="text-xs text-muted">
                      {LEVEL_TITLES[item.level]} · {READINESS_STATUS[item.status].label}
                    </span>
                  </span>
                  {item.reason && <span className="text-muted wrap-anywhere">{item.reason}</span>}
                  {blocks.length > 0 && (
                    <span className="wrap-anywhere">Влияет на: {blocks.join(', ')}</span>
                  )}
                  {notBlocks.length > 0 && (
                    <span className="text-muted wrap-anywhere">
                      Не влияет на: {notBlocks.join(', ')}
                    </span>
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
