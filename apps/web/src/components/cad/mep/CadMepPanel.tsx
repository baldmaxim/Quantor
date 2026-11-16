'use client';

import type { FC, ReactNode } from 'react';

import type { IWorkspaceCadMep } from '@/components/workspace/cad/types';
import { Button, InspectorSection } from '@/components/ui';

import { CadMepApproval } from './CadMepApproval';
import { CadMepBuild } from './CadMepBuild';
import { CadMepRoute } from './CadMepRoute';
import { CadMepRouteList } from './CadMepRouteList';
import { CadMepSpec } from './CadMepSpec';

interface ICadMepPanelProps {
  /** Реестр стояков по ИОС - вход построения трасс; показан свёрнутым перед построением. */
  readonly risers?: ReactNode;
}

const HEADING = 'text-micro font-semibold tracking-[0.06em] text-muted uppercase';

/**
 * Вкладка «Трассы» правой панели: одобрить вид, одной кнопкой построить трассы механики и ЭОМ/СС,
 * открыть построенные, принять этаж целиком и скачать 3D DXF; общая спецификация всех систем.
 * Каждый шаг - решение человека; результат генераторов до принятия - кандидат. Трассы движка закрыты
 * флагом `cad.mep_engine` (ADR-0051): выключен - остаётся одно одобрение вида.
 */
export const CadMepPanel: FC<IWorkspaceCadMep & ICadMepPanelProps> = ({
  parent,
  approval,
  revokedDecisions,
  routeJobs,
  route,
  openRemarks,
  onSelectRoute,
  sections = null,
  engineRoutes = true,
  risers,
}) => (
  <div className="flex min-w-0 flex-col gap-[var(--s-6)]" data-testid="cad-mep">
    <InspectorSection title="1. Одобрение вида">
      <CadMepApproval
        parent={parent}
        approval={approval}
        // На трассах открытые замечания относятся к route-заданию, а вид к тому времени одобрен.
        openRemarks={route ? null : openRemarks}
        revoked={revokedDecisions}
        routeJobs={routeJobs}
      />
    </InspectorSection>

    {engineRoutes && (
      <>
        <InspectorSection title="2. Построить трассы, ЭОМ и СС">
          <div className="flex min-w-0 flex-col gap-[var(--s-4)]">
            {risers && (
              <details className="flex min-w-0 flex-col gap-[var(--s-2)]">
                <summary
                  className={`${HEADING} min-h-[32px] cursor-pointer content-center max-md:min-h-[44px]`}
                >
                  Реестр стояков по ИОС — вход построения
                </summary>
                <div className="min-w-0 pt-[var(--s-3)]">{risers}</div>
              </details>
            )}
            {approval ? (
              <CadMepBuild
                parent={parent}
                onCreated={onSelectRoute}
                hasRoutes={routeJobs.some((item) => item.approval_id === approval.id)}
                knownRouteJobIds={routeJobs.map((item) => item.job_id)}
                sections={sections}
              />
            ) : (
              <p className="text-xs text-muted">Трассы строятся только по одобренному виду.</p>
            )}
          </div>
        </InspectorSection>

        <InspectorSection title="3. Трассы вида">
          <div className="flex min-w-0 flex-col gap-[var(--s-4)]">
            <CadMepRouteList
              routeJobs={routeJobs}
              selectedId={route?.summaryId ?? null}
              onSelect={onSelectRoute}
            />
            {route && (
              <Button
                onClick={() => onSelectRoute(null)}
                className="self-start max-md:h-[44px] max-md:w-full"
              >
                Закрыть трассы
              </Button>
            )}
            {route && <CadMepRoute route={route} parent={parent} openRemarks={openRemarks} />}
          </div>
        </InspectorSection>

        <InspectorSection title="4. Спецификация">
          {approval ? (
            <CadMepSpec parent={parent} routeParams={route?.params ?? null} />
          ) : (
            <p className="text-xs text-muted">Спецификация появится после построения по одобренному виду.</p>
          )}
        </InspectorSection>
      </>
    )}
  </div>
);
