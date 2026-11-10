'use client';

import type { CadDecisionRead } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { Button } from '@/components/ui';
import { approveBlock, mepErrorText } from '@/lib/cad/mep-gates';
import { useApproveCadView } from '@/lib/cad/mep-queries';
import type { ICadViewParams } from '@/lib/cad/view-queries';

import { CadMepDecision } from './CadMepDecision';

interface ICadMepApprovalProps {
  /** Вид родителя: задание, попытка с результатом, лист, вид. */
  parent: ICadViewParams;
  approval: CadDecisionRead | null;
  /** Открытые замечания вида; `null` - ещё не прочитаны. */
  openRemarks: number | null;
}

/** Шаг 1: «Одобрить вид». Одобрение - решение человека, без него трассы не строятся. */
export const CadMepApproval: FC<ICadMepApprovalProps> = ({ parent, approval, openRemarks }) => {
  const approve = useApproveCadView(parent);
  const [problem, setProblem] = useState<string | null>(null);

  if (approval) return <CadMepDecision title="Вид одобрен" decision={approval} />;

  const block = approveBlock(approval, openRemarks);

  return (
    <div className="flex min-w-0 flex-col items-start gap-[var(--s-3)]">
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
