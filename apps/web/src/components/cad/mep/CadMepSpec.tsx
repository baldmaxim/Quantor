'use client';

import type { FC } from 'react';

import { useCadEomJob, useCadEomRoutes3d } from '@/lib/cad/eom-queries';
import { useCadCandidate } from '@/lib/cad/mep-queries';
import { buildSpec, type ISpecSystem } from '@/lib/cad/mep-spec';
import type { ICadViewParams } from '@/lib/cad/view-queries';

const EOM_STATUS_TEXT: Readonly<Record<string, string>> = {
  queued: 'в очереди',
  running: 'строятся',
  succeeded: 'построены',
  failed: 'не построены',
  cancelled: 'отменено',
};

interface ICadMepSpecProps {
  /** Одобренный вид: по нему строятся ЭОМ и СС. */
  parent: ICadViewParams;
  /** Открытые трассы механики (route-задание с результатом); `null` - трассы не открыты. */
  routeParams: ICadViewParams | null;
}

const HEAD = 'px-[var(--s-3)] py-[var(--s-2)] text-xs font-normal text-muted';

const SpecSystem: FC<{ system: ISpecSystem }> = ({ system }) => (
  <details className="min-w-0 border-b border-border last:border-b-0" data-testid="spec-system">
    <summary className="flex min-h-[44px] cursor-pointer items-center justify-between gap-[var(--s-3)] text-sm">
      <span className="min-w-0 [overflow-wrap:anywhere]">{system.label}</span>
      <span className="shrink-0 tabular text-xs text-muted">{system.summary}</span>
    </summary>
    {system.rows.length === 0 ? (
      <p className="pb-[var(--s-3)] text-xs text-muted">Разбивки по позициям нет.</p>
    ) : (
      <div className="min-w-0 overflow-x-auto pb-[var(--s-3)]">
        <table className="w-full min-w-[220px] border-collapse text-xs" aria-label={`Спецификация: ${system.label}`}>
          <thead>
            <tr className="border-b border-border">
              <th scope="col" className={`${HEAD} text-left`}>
                Позиция
              </th>
              <th scope="col" className={`${HEAD} text-right`}>
                Кол-во
              </th>
            </tr>
          </thead>
          <tbody>
            {system.rows.map((row) => (
              <tr key={row.key} className="border-b border-border last:border-b-0" title={row.hint ?? undefined}>
                <th
                  scope="row"
                  className="px-[var(--s-3)] py-[var(--s-2)] text-left font-normal [overflow-wrap:anywhere]"
                >
                  {row.item}
                </th>
                <td className="whitespace-nowrap px-[var(--s-3)] py-[var(--s-2)] text-right tabular">
                  {row.qty} {row.unit}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    )}
  </details>
);

/**
 * Общая спецификация вида: механика и ЭОМ/СС одним списком систем, каждая раскрывается. Длины
 * механики - из итогов открытых трасс, позиции ЭОМ и СС - из ведомости генератора. Кандидат: до
 * принятия человеком в работу не идёт.
 */
export const CadMepSpec: FC<ICadMepSpecProps> = ({ parent, routeParams }) => {
  const candidate = useCadCandidate(routeParams ?? parent, routeParams !== null);
  const eomJob = useCadEomJob(parent, true);
  const eom = useCadEomRoutes3d(parent, true);
  const job = eomJob.data ?? null;
  const quantities = eom.status === 'ready' ? (eom.data.quantities ?? []) : [];
  const issues = eom.status === 'ready' ? (eom.data.issues ?? []) : [];
  const systems = buildSpec(routeParams !== null && candidate.data ? candidate.data : null, quantities);

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-4)]" data-testid="mep-spec">
      <p className="text-xs text-muted">Кандидат генераторов: до принятия человеком в работу не идёт.</p>
      <ul className="flex flex-col gap-[var(--s-1)] text-xs text-muted" aria-label="Состав спецификации">
        <li>
          Трассы:{' '}
          {routeParams === null
            ? 'откройте построенные трассы в разделе 3.'
            : candidate.isPending
              ? 'загрузка итогов…'
              : candidate.isError
                ? 'итоги не загружены.'
                : 'по итогам открытых трасс.'}
        </li>
        <li data-testid="spec-eom-status">
          ЭОМ и СС:{' '}
          {job === null
            ? eomJob.isPending
              ? 'загрузка…'
              : 'ещё не строились.'
            : `${EOM_STATUS_TEXT[job.status] ?? job.status}${job.generator_version ? ` · ${job.generator_version}` : ''}`}
          {job?.status === 'failed' && job.error_message ? ` — ${job.error_message}` : ''}
          {eom.status === 'ready' && eom.data.apartments != null ? ` · квартир: ${eom.data.apartments}` : ''}
        </li>
      </ul>
      {systems.length === 0 ? (
        <p className="text-xs text-muted">Позиций пока нет.</p>
      ) : (
        <div className="flex min-w-0 flex-col" aria-label="Системы">
          {systems.map((system) => (
            <SpecSystem key={system.key} system={system} />
          ))}
        </div>
      )}
      {issues.length > 0 && (
        <details className="text-xs text-muted">
          <summary className="flex min-h-[44px] cursor-pointer items-center">
            Замечания генератора ЭОМ и СС: {issues.length}
          </summary>
          <ul className="list-disc pl-[var(--s-6)]">
            {issues.map((text) => (
              <li key={text} className="[overflow-wrap:anywhere]">
                {text}
              </li>
            ))}
          </ul>
        </details>
      )}
    </div>
  );
};
