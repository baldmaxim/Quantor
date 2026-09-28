'use client';

import type { CalcPassportSummaryRead, CalcVkReadinessRead } from '@quantor/api-client';

import { Button, EmptyState, StatusBadge } from '@/components/ui';
import { PASSPORT_STATUS, SEMANTICS } from '@/lib/calc/vk';

/**
 * Обзор комплекта ВК: по каждой системе — статус, закрытость исходных данных, что Quantor
 * рассчитал и главные проблемы. Частичный результат показывается, а не прячется; итоговой
 * «суммы всего» нет.
 */

interface IVkOverviewProps {
  passports: CalcPassportSummaryRead[];
  readiness: CalcVkReadinessRead | undefined;
  onOpen: (systemCode: string) => void;
}

export const VkOverview = ({ passports, readiness, onOpen }: IVkOverviewProps) => {
  if (passports.length === 0) {
    return (
      <EmptyState
        compact
        title="Комплект ВК ещё не рассчитывался"
        description="Укажите корпус и нажмите «Рассчитать ВК»: Quantor соберёт найденные данные и покажет, чего не хватает."
      />
    );
  }
  return (
    <ul className="grid list-none gap-[var(--s-4)] md:grid-cols-2">
      {passports.map((passport) => {
        const system = readiness?.systems.find((item) => item.system_code === passport.system_code);
        const status = PASSPORT_STATUS[passport.status];
        return (
          <li
            key={passport.id}
            className="flex flex-col gap-[var(--s-3)] rounded-[var(--radius-md)] border border-border-strong bg-surface px-[var(--s-5)] py-[var(--s-4)]"
          >
            <header className="flex flex-wrap items-center gap-[var(--s-3)]">
              <h3 className="text-base font-medium">{passport.system_code}</h3>
              <span className="min-w-0 flex-1 text-sm text-muted wrap-anywhere">
                {passport.system_title}
              </span>
              <StatusBadge tone={status.tone}>{status.label}</StatusBadge>
            </header>
            {system && (
              <p className="text-sm wrap-anywhere">
                Исходные: обязательных {system.inputs.required_satisfied} из{' '}
                {system.inputs.required_total}; найдено автоматически {system.inputs.found_auto},
                выводится {system.inputs.derivable}, нужен человек {system.inputs.needs_human}
                {system.inputs.not_inspected > 0 && `, не проверено ${system.inputs.not_inspected}`}
                .{' '}
                <StatusBadge tone={SEMANTICS[system.semantics].tone}>
                  {SEMANTICS[system.semantics].label}
                </StatusBadge>
              </p>
            )}
            {passport.highlights.length > 0 && (
              <section className="flex flex-col gap-[var(--s-1)]">
                <h4 className="text-xs font-medium text-muted">Quantor рассчитал</h4>
                <ul className="flex list-disc flex-col gap-[var(--s-1)] pl-[var(--s-5)] text-sm">
                  {passport.highlights.map((line) => (
                    <li key={line} className="wrap-anywhere">
                      {line}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            {passport.problems.length > 0 && (
              <section className="flex flex-col gap-[var(--s-1)]">
                <h4 className="text-xs font-medium text-muted">Главные проблемы</h4>
                <ul className="flex list-disc flex-col gap-[var(--s-1)] pl-[var(--s-5)] text-sm">
                  {passport.problems.map((line) => (
                    <li key={line} className="wrap-anywhere">
                      {line}
                    </li>
                  ))}
                </ul>
              </section>
            )}
            <div>
              <Button compact onClick={() => onOpen(passport.system_code)}>
                Паспорт {passport.system_code}
              </Button>
            </div>
          </li>
        );
      })}
    </ul>
  );
};
