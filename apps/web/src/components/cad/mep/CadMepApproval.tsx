'use client';

import type { CadDecisionRead, CadRouteJobRead } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { Button } from '@/components/ui';
import { approveBlock, mepErrorText } from '@/lib/cad/mep-gates';
import { useApproveCadView } from '@/lib/cad/mep-queries';
import type { ICadViewParams } from '@/lib/cad/view-queries';

import { CadMepDecision, CadMepRevoked } from './CadMepDecision';
import { CadMepRevoke } from './CadMepRevoke';

interface ICadMepApprovalProps {
  /** Вид родителя: задание, попытка с результатом, лист, вид. */
  parent: ICadViewParams;
  approval: CadDecisionRead | null;
  /** Открытые замечания вида; `null` - ещё не прочитаны. */
  openRemarks: number | null;
  /** Отозванные одобрения вида, старые сверху. */
  revoked?: readonly CadDecisionRead[];
  /** Route-задания вида: по ним видно, приняты ли трассы по этому одобрению. */
  routeJobs?: readonly CadRouteJobRead[];
}

/** Шаг 1: «Одобрить вид». Одобрение - решение человека, без него трассы не строятся. */
export const CadMepApproval: FC<ICadMepApprovalProps> = ({
  parent,
  approval,
  openRemarks,
  revoked = [],
  routeJobs = [],
}) => {
  const approve = useApproveCadView(parent);
  const [problem, setProblem] = useState<string | null>(null);

  if (approval) {
    const accepted = routeJobs.some((route) => route.accepted && route.approval_id === approval.id);
    return (
      <div className="flex min-w-0 flex-col gap-[var(--s-3)]">
        <CadMepDecision title="Вид одобрен" decision={approval}>
          <CadMepRevoke
            params={parent}
            decision={approval}
            label="Отозвать одобрение"
            consequence="Трассы по этому виду больше нельзя будет строить и принимать, пока вид не одобрен заново. Запись об одобрении сохранится."
            blockedReason={
              accepted ? 'По этому одобрению приняты трассы: сначала отзовите принятие.' : null
            }
          />
        </CadMepDecision>
        <CadMepRevoked decisions={revoked} />
      </div>
    );
  }

  const block = approveBlock(approval, openRemarks);

  return (
    <div className="flex min-w-0 flex-col items-start gap-[var(--s-3)]">
      <CadMepRevoked decisions={revoked} />
      <Button
        variant="primary"
        loading={approve.isPending}
        disabled={block !== null}
        onClick={() => {
          setProblem(null);
          approve.mutate({}, { onError: (error) => setProblem(mepErrorText(error)) });
        }}
        className="max-md:h-[44px] max-md:w-full"
      >
        Одобрить вид
      </Button>
      {block && (
        <p className="text-xs text-muted" role="note">
          {block}
        </p>
      )}
      {problem && (
        <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
          {problem}
        </p>
      )}
    </div>
  );
};
