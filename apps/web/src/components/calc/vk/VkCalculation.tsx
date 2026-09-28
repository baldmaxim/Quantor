'use client';

import type { CalcPassportRead } from '@quantor/api-client';

import { StatusBadge } from '@/components/ui';
import { LAYER_TITLES, RULE_READINESS, amountText } from '@/lib/calc/vk';

/**
 * Расчёт: результаты ядра по слоям, сверки «документ — контроль» и готовность инженерных
 * решений. Документальное значение не заменяется расчётом: расхождение видно отдельно.
 */

export const VkCalculation = ({ passport }: { passport: CalcPassportRead }) => {
  const { calculation, checks, rules } = passport.body;
  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      <section className="flex flex-col gap-[var(--s-2)]">
        <h3 className="text-sm font-medium">Результаты расчёта (сценарий «Ожидаемый»)</h3>
        {calculation.length === 0 ? (
          <p className="text-sm text-muted">Расчёт не выполнялся — см. «Неопределённости».</p>
        ) : (
          <ul className="flex list-none flex-col divide-y divide-border rounded-[var(--radius-sm)] border border-border text-sm">
            {calculation.map((result) => (
              <li
                key={result.key}
                className="flex flex-col gap-[var(--s-1)] px-[var(--s-4)] py-[var(--s-2)]"
              >
                <span className="flex flex-wrap items-center gap-[var(--s-3)]">
                  <span className="min-w-0 flex-1 font-medium wrap-anywhere">{result.title}</span>
                  <span className="text-xs text-muted">
                    {LAYER_TITLES[result.layer] ?? result.layer}
                  </span>
                  <span className="font-mono">{amountText(result.amount, result.unit)}</span>
                </span>
                {result.explanation && (
                  <span className="text-xs text-muted wrap-anywhere">{result.explanation}</span>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
      <section className="flex flex-col gap-[var(--s-2)]">
        <h3 className="text-sm font-medium">Документ и контрольный расчёт</h3>
        <ul className="flex list-none flex-col gap-[var(--s-2)] text-sm">
          {checks.map((check) => (
            <li
              key={check.title}
              className="rounded-[var(--radius-sm)] border border-border px-[var(--s-4)] py-[var(--s-2)] wrap-anywhere"
            >
              <span className="font-medium">{check.title}</span>: документ{' '}
              {check.document_value ?? '—'}, контроль {check.check_value ?? '—'}, расхождение{' '}
              {check.discrepancy ?? '—'} — <span className="text-muted">{check.status}</span>
            </li>
          ))}
        </ul>
      </section>
      <section className="flex flex-col gap-[var(--s-2)]">
        <h3 className="text-sm font-medium">Инженерные решения калькулятора</h3>
        <ul className="flex list-none flex-col divide-y divide-border rounded-[var(--radius-sm)] border border-border text-sm">
          {rules.map((rule) => (
            <li
              key={rule.rule_key}
              className="flex flex-col gap-[var(--s-1)] px-[var(--s-4)] py-[var(--s-2)]"
            >
              <span className="flex flex-wrap items-center gap-[var(--s-3)]">
                <span className="min-w-0 flex-1 wrap-anywhere">{rule.title}</span>
                <StatusBadge tone={RULE_READINESS[rule.status].tone}>
                  {RULE_READINESS[rule.status].label}
                  {rule.version != null && ` · v${rule.version}`}
                </StatusBadge>
              </span>
              <span className="font-mono text-xs text-muted wrap-anywhere">{rule.rule_key}</span>
              <span className="text-xs text-muted wrap-anywhere">Без него: {rule.blocks}</span>
            </li>
          ))}
        </ul>
      </section>
    </div>
  );
};
