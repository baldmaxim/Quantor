'use client';

import type { CalcRuleSummaryRead, CalcVkRuleNeedRead } from '@quantor/api-client';
import { useMemo, useState } from 'react';

import { RuleDecisionDialog, type IRuleDecisionTarget } from '@/components/calc/RuleDecisionDialog';
import { RuleReviewDialog, type IRuleReviewTarget } from '@/components/calc/RuleReviewDialog';
import {
  Button,
  EmptyState,
  ErrorState,
  SkeletonRows,
  StatusBadge,
  type BadgeTone,
} from '@/components/ui';
import { needState, type NeedState } from '@/lib/calc/rule-needs';
import { useVkRuleNeeds } from '@/lib/calc/rule-needs-queries';
import { useCalcRules } from '@/lib/calc/queries';
import { useHasPermission, useSession } from '@/lib/session';

/**
 * Решения инженера для калькуляторов ВК: какие правила нужны, что без них не определяется и
 * где каждое сейчас. Инженер вносит черновик, другой человек его утверждает — только тогда
 * правило идёт в расчёт. Нужные для гейта — сверху.
 */

const STATE_VIEW: Readonly<
  Record<NeedState['kind'], (state: NeedState) => { label: string; tone: BadgeTone }>
> = {
  not_implemented: () => ({ label: 'методика не реализована', tone: 'neutral' }),
  none: () => ({ label: 'нет решения', tone: 'warning' }),
  draft: (state) => ({
    label: `черновик v${state.kind === 'draft' ? state.version : ''} — ждёт проверки`,
    tone: 'accent',
  }),
  approved: (state) => ({
    label: `утверждено v${state.kind === 'approved' ? state.version : ''}`,
    tone: 'success',
  }),
  closed: () => ({ label: 'отклонено или выведено — нужно новое решение', tone: 'warning' }),
};

export const RuleNeeds = () => {
  const needs = useVkRuleNeeds(true);
  const rules = useCalcRules(true);
  const canEdit = useHasPermission('calc.edit');
  const canVerify = useHasPermission('calc.verify');
  const userId = useSession().data?.user?.id ?? undefined;
  const [decision, setDecision] = useState<IRuleDecisionTarget | null>(null);
  const [review, setReview] = useState<IRuleReviewTarget | null>(null);
  const summaries = useMemo(
    () => new Map((rules.data ?? []).map((item) => [item.rule_key, item])),
    [rules.data],
  );

  if (needs.isError || rules.isError) {
    return (
      <ErrorState
        title="Заявки правил не загрузились"
        onRetry={() => {
          void needs.refetch();
          void rules.refetch();
        }}
      />
    );
  }
  if (!needs.data || !rules.data) return <SkeletonRows rows={6} />;
  if (needs.data.length === 0) return <EmptyState compact title="Заявок нет" />;

  return (
    <div className="flex flex-col gap-[var(--s-4)]">
      <p className="max-w-[80ch] text-sm text-muted">
        Числа в правила вносит инженер со ссылкой на источник. Черновик утверждает другой человек с
        правом проверки; утверждённая версия не меняется — изменение оформляется новой версией.
      </p>
      <ul className="flex list-none flex-col gap-[var(--s-3)]">
        {needs.data.map((need) => (
          <NeedRow
            key={need.rule_key}
            need={need}
            summary={summaries.get(need.rule_key)}
            canEdit={canEdit}
            canVerify={canVerify}
            onDecide={(state) => setDecision({ need, state })}
            onReview={(version) => setReview({ ruleKey: need.rule_key, version })}
          />
        ))}
      </ul>
      <RuleDecisionDialog target={decision} onClose={() => setDecision(null)} />
      <RuleReviewDialog target={review} currentUserId={userId} onClose={() => setReview(null)} />
    </div>
  );
};

const DECIDE_LABEL: Readonly<Record<NeedState['kind'], string>> = {
  none: 'Внести решение',
  closed: 'Внести решение',
  draft: 'Править черновик',
  approved: 'Новая версия',
  not_implemented: '',
};

const NeedRow = ({
  need,
  summary,
  canEdit,
  canVerify,
  onDecide,
  onReview,
}: {
  need: CalcVkRuleNeedRead;
  summary: CalcRuleSummaryRead | undefined;
  canEdit: boolean;
  canVerify: boolean;
  onDecide: (state: NeedState) => void;
  onReview: (version: number) => void;
}) => {
  const state = needState(need, summary);
  const view = STATE_VIEW[state.kind](state);
  return (
    <li className="flex flex-col gap-[var(--s-2)] rounded-[var(--radius-md)] border border-border-strong bg-surface px-[var(--s-5)] py-[var(--s-4)] text-sm">
      <span className="flex flex-wrap items-center gap-x-[var(--s-3)] gap-y-[var(--s-1)]">
        <span className="min-w-0 font-medium wrap-anywhere">{need.title}</span>
        {need.gate && <StatusBadge tone="danger">нужно для гейта</StatusBadge>}
        <StatusBadge tone={view.tone} wrap>
          {view.label}
        </StatusBadge>
      </span>
      <span className="font-mono text-xs text-muted wrap-anywhere">
        {need.rule_key} · {need.systems.join(', ')}
      </span>
      <span className="text-muted wrap-anywhere">Без решения не определяется: {need.blocks}.</span>
      {summary && summary.sources.length > 0 && (
        <span className="text-xs text-muted wrap-anywhere">
          Основание: {summary.sources.join('; ')}
        </span>
      )}
      {state.kind !== 'not_implemented' && (canEdit || canVerify) && (
        <span className="flex flex-wrap gap-[var(--s-3)]">
          {canEdit && (
            <Button compact onClick={() => onDecide(state)}>
              {DECIDE_LABEL[state.kind]}
            </Button>
          )}
          {canVerify && state.kind === 'draft' && (
            <Button compact onClick={() => onReview(state.version)}>
              Проверить
            </Button>
          )}
        </span>
      )}
    </li>
  );
};
