'use client';

import { useState, type FC } from 'react';

import { Button } from '@/components/ui';
import { useBuildEom, useCadEomJob, useCadEomRoutes3d } from '@/lib/cad/eom-queries';
import { mepErrorText } from '@/lib/cad/mep-gates';
import type { ICadViewParams } from '@/lib/cad/view-queries';

const STATUS_TEXT: Readonly<Record<string, string>> = {
  queued: 'в очереди',
  running: 'строится',
  succeeded: 'построены',
  failed: 'не построены',
  cancelled: 'отменено',
};

interface ICadEomBuildProps {
  parent: ICadViewParams;
}

/**
 * «ЭОМ и СС этажа»: по тому же одобренному виду, отметке и уровням, что трассы механики, генератор
 * `cad_eom` ставит щиты, приборы, питающие и групповые линии, лоток и вводы СС. Результат -
 * кандидат: слои ЭОМ и СС появляются в 3D этажа (панель «Слои»), ведомость - ниже.
 */
export const CadEomBuild: FC<ICadEomBuildProps> = ({ parent }) => {
  const build = useBuildEom(parent);
  const job = useCadEomJob(parent, true);
  const routes = useCadEomRoutes3d(parent, true);
  const [problem, setProblem] = useState<string | null>(null);
  const current = job.data ?? null;
  const quantities = routes.status === 'ready' ? (routes.data.quantities ?? []) : [];
  const issues = routes.status === 'ready' ? (routes.data.issues ?? []) : [];
  const busy = build.isPending || current?.status === 'queued' || current?.status === 'running';

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-4)]" data-testid="cad-eom">
      <Button
        onClick={() => {
          setProblem(null);
          build.mutate(undefined, { onError: (error) => setProblem(mepErrorText(error)) });
        }}
        disabled={busy}
        className="self-start max-md:h-[44px] max-md:w-full"
      >
        {current?.status === 'succeeded' ? 'Перестроить ЭОМ и СС' : 'Построить ЭОМ и СС'}
      </Button>
      {current && (
        <p className="text-xs text-muted" role="status">
          ЭОМ и СС: {STATUS_TEXT[current.status] ?? current.status}
          {current.generator_version ? ` · ${current.generator_version}` : ''}
          {current.status === 'failed' && current.error_message ? ` — ${current.error_message}` : ''}
        </p>
      )}
      {problem && (
        <p className="text-xs text-[var(--danger)]" role="alert">
          {problem}
        </p>
      )}
      {routes.status === 'ready' && (
        <div className="flex min-w-0 flex-col gap-[var(--s-2)]">
          <p className="text-xs text-muted">
            Квартир: {routes.data.apartments ?? '—'} · линий: {routes.data.polylines.length} ·
            приборов и щитов: {routes.data.elements.length}. Слои — в 3D этажа, группы «Электроснабжение ЭОМ»
            и «Слаботочные системы СС».
          </p>
          {quantities.length > 0 && (
            <table className="w-full text-xs" aria-label="Ведомость ЭОМ и СС этажа">
              <thead>
                <tr className="text-left text-muted">
                  <th className="font-normal">Система</th>
                  <th className="font-normal">Позиция</th>
                  <th className="text-right font-normal">Кол-во</th>
                </tr>
              </thead>
              <tbody>
                {quantities.map((row) => (
                  <tr key={`${row.system}|${row.item}`} title={row.formula ?? row.source ?? undefined}>
                    <td className="pr-[var(--s-2)] align-top">{row.system}</td>
                    <td className="pr-[var(--s-2)] align-top">{row.item}</td>
                    <td className="whitespace-nowrap text-right align-top">
                      {Number.isInteger(row.qty) ? row.qty : row.qty.toFixed(1)} {row.unit}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {issues.length > 0 && (
            <details className="text-xs text-muted">
              <summary>Замечания генератора: {issues.length}</summary>
              <ul className="list-disc pl-[var(--s-6)]">
                {issues.map((text) => (
                  <li key={text}>{text}</li>
                ))}
              </ul>
            </details>
          )}
        </div>
      )}
    </div>
  );
};
