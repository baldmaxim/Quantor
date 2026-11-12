'use client';

import type { FC } from 'react';

import type { IWorkspaceCadMep } from '@/components/workspace/cad/types';
import { Button, InspectorSection } from '@/components/ui';

import { CadMepApproval } from './CadMepApproval';
import { CadMepBuild } from './CadMepBuild';
import { CadMepRoute } from './CadMepRoute';
import { CadMepRouteList } from './CadMepRouteList';

/**
 * Вкладка «Трассы» правой панели: одобрить вид, построить трассы, открыть построенные, принять
 * этаж целиком и скачать 3D DXF. Каждый шаг - решение человека; трассы до принятия - кандидат.
 */
export const CadMepPanel: FC<IWorkspaceCadMep> = ({
  parent,
  approval,
  revokedDecisions,
  routeJobs,
  route,
  openRemarks,
  onSelectRoute,
  sections = null,
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

    <InspectorSection title="2. Построить трассы">
      {approval ? (
        <CadMepBuild
          parent={parent}
          onCreated={onSelectRoute}
          hasRoutes={routeJobs.some((item) => item.approval_id === approval.id)}
          sections={sections}
        />
      ) : (
        <p className="text-xs text-muted">Трассы строятся только по одобренному виду.</p>
      )}
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
  </div>
);
