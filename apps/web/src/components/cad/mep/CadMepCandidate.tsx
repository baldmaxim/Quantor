'use client';

import type { FC } from 'react';

import { InspectorSection } from '@/components/ui';
import {
  assumptionValueText,
  formatMeters,
  mepSystemLabel,
  type MepCandidate,
  MEP_SYSTEMS,
} from '@/lib/cad/mep-candidate';
import { mepLayerDef } from '@/lib/cad/mep-layers';
import { useCadCandidate } from '@/lib/cad/mep-queries';
import { cadViewErrorText, type ICadViewParams } from '@/lib/cad/view-queries';
import { extractCode } from '@/lib/errors';

interface ICadMepCandidateProps {
  /** Route-задание, его попытка с результатом, лист и вид. */
  params: ICadViewParams;
}

const CELL = 'px-[var(--s-3)] py-[var(--s-2)] text-right tabular';
const HEAD = 'px-[var(--s-3)] py-[var(--s-2)] text-right text-xs font-normal text-muted';

const LengthTable: FC<{
  caption: string;
  rows: readonly { key: string; label: string; plan: number; len3d: number }[];
}> = ({ caption, rows }) => (
  <div className="min-w-0 overflow-x-auto">
    <table className="w-full min-w-[260px] border-collapse text-xs">
      <caption className="pb-[var(--s-2)] text-left text-xs text-muted">{caption}</caption>
      <thead>
        <tr className="border-b border-border">
          <th scope="col" className={`${HEAD} text-left`}>
            &nbsp;
          </th>
          <th scope="col" className={HEAD}>
            План, м
          </th>
          <th scope="col" className={HEAD}>
            3D, м
          </th>
        </tr>
      </thead>
      <tbody>
        {rows.map((row) => (
          <tr key={row.key} className="border-b border-border last:border-b-0">
            <th scope="row" className="px-[var(--s-3)] py-[var(--s-2)] text-left font-normal [overflow-wrap:anywhere]">
              {row.label}
            </th>
            <td className={CELL}>{formatMeters(row.plan)}</td>
            <td className={CELL}>{formatMeters(row.len3d)}</td>
          </tr>
        ))}
      </tbody>
    </table>
  </div>
);

const Body: FC<{ candidate: MepCandidate }> = ({ candidate }) => {
  const { routes, apartments, issues, assumptions, notes, elevation } = candidate;

  const systems = MEP_SYSTEMS.filter((item) => routes.by_system[item.key] !== undefined).map(
    (item) => ({
      key: item.key,
      label: item.label,
      plan: routes.by_system[item.key]?.plan_m ?? 0,
      len3d: routes.by_system[item.key]?.len3d_m ?? 0,
    }),
  );
  const layers = Object.entries(routes.by_layer).map(([name, value]) => ({
    key: name,
    label: `${mepLayerDef(name)?.label ?? name} · ${name}`,
    plan: value.plan_m,
    len3d: value.len3d_m,
  }));
  const withApartments = apartments.filter((apartment) =>
    Object.keys(apartment.lengths_own_lines).length > 0,
  );

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-5)]" data-testid="mep-candidate">
      <p className="text-xs text-muted">
        Кандидат генератора: до принятия человеком в работу не идёт. Отметка пола{' '}
        {elevation.floor_elevation_mm.value} мм, высота этажа {elevation.floor_height_mm.value} мм
        (ввод оператора).
      </p>

      <LengthTable
        caption="Итого по системам"
        rows={[
          ...systems,
          { key: 'total', label: 'Всего', plan: routes.totals.plan_m, len3d: routes.totals.len3d_m },
        ]}
      />
      <LengthTable caption="По слоям" rows={layers} />

      {withApartments.map((apartment) => (
        <LengthTable
          key={apartment.idx}
          caption={`Квартира ${apartment.number ?? apartment.idx}`}
          rows={Object.entries(apartment.lengths_own_lines).map(([key, value]) => ({
            key,
            label: mepSystemLabel(key),
            plan: value.plan_m,
            len3d: value.len3d_m,
          }))}
        />
      ))}

      <div className="flex min-w-0 flex-col gap-[var(--s-2)]">
        <h4 className="text-sm font-medium">Проблемы ({issues.length})</h4>
        {issues.length === 0 ? (
          <p className="text-xs text-muted">Генератор проблем не отметил.</p>
        ) : (
          <ul className="flex flex-col gap-[var(--s-2)]" aria-label="Проблемы генератора">
            {issues.map((issue, index) => (
              <li
                key={`${issue.code}-${index}`}
                className="rounded-[var(--radius-sm)] border border-warning-soft bg-warning-soft px-[var(--s-4)] py-[var(--s-3)] text-xs [overflow-wrap:anywhere]"
              >
                <span className="mono">{issue.code}</span>
                {issue.apartment !== null && issue.apartment !== undefined && (
                  <span> · {issue.apartment}</span>
                )}
                <span className="block">{issue.message}</span>
              </li>
            ))}
          </ul>
        )}
        {notes.length > 0 && (
          <ul className="list-disc pl-[var(--s-6)] text-xs text-muted" aria-label="Примечания генератора">
            {notes.map((note, index) => (
              <li key={`${index}-${note}`} className="[overflow-wrap:anywhere]">
                {note}
              </li>
            ))}
          </ul>
        )}
      </div>

      <details className="min-w-0">
        <summary className="flex min-h-[44px] cursor-pointer items-center text-sm font-medium">
          Допущения ({assumptions.length})
        </summary>
        <p className="pb-[var(--s-3)] text-xs text-muted">
          Параметры, принятые генератором без наблюдения на чертеже: проверьте их до принятия.
        </p>
        <ul className="flex flex-col gap-[var(--s-2)]" aria-label="Допущения">
          {assumptions.map((item) => (
            <li key={item.name} className="text-xs [overflow-wrap:anywhere]">
              <span className="mono">{item.name}</span> = {assumptionValueText(item.value)}
              {item.unit ? ` ${item.unit}` : ''}
              {item.note && <span className="block text-muted">{item.note}</span>}
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
};

/** Длины по системам, слоям и квартирам, проблемы и допущения из `candidate.json` трасс. */
export const CadMepCandidate: FC<ICadMepCandidateProps> = ({ params }) => {
  const query = useCadCandidate(params, true);

  return (
    <InspectorSection title="Итоги генератора">
      {query.isPending ? (
        <p role="status" className="text-xs text-muted">
          Загрузка итогов…
        </p>
      ) : query.isError ? (
        <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
          Итоги не загружены.{' '}
          {extractCode(query.error) === 'CAD_CANDIDATE_INVALID'
            ? 'Файл candidate.json не соответствует схеме quantor.cad_mep.candidate.v1.'
            : cadViewErrorText(query.error).text}
        </p>
      ) : (
        <Body candidate={query.data} />
      )}
    </InspectorSection>
  );
};
