'use client';

import type { CalcRuleType, CalcRuleVersionRead, CalcVkRuleNeedRead } from '@quantor/api-client';
import { useId, useState } from 'react';

import { FIELD, RuleSourceFields, TEXTAREA } from '@/components/calc/RuleSourceFields';
import { Button, Dialog, DialogActions, ErrorState, SkeletonRows } from '@/components/ui';
import { unitTitle } from '@/lib/calc/format';
import { RULE_TYPE_TITLES } from '@/lib/calc/rules';
import {
  SOURCE_KINDS,
  buildDecision,
  offeredTypes,
  parameterValues,
  sourcePrefill,
  type NeedState,
  type SourceKind,
} from '@/lib/calc/rule-needs';
import { useCalcRuleDetail, useSaveRuleDecision } from '@/lib/calc/rule-needs-queries';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

/**
 * Решение инженера по заявке калькулятора: значения параметров, основание, ограничения.
 *
 * Записывается черновик версии правила. В расчёт он не идёт, пока его не утвердит другой
 * человек с правом проверки. Числа вносит инженер — Quantor не подставляет ни нормы, ни примеры.
 */

export interface IRuleDecisionTarget {
  need: CalcVkRuleNeedRead;
  state: NeedState;
}

const TITLES: Readonly<Record<NeedState['kind'], string>> = {
  none: 'Решение инженера',
  draft: 'Править черновик',
  approved: 'Новая версия правила',
  closed: 'Решение инженера',
  not_implemented: 'Решение инженера',
};

export const RuleDecisionDialog = ({
  target,
  onClose,
}: {
  target: IRuleDecisionTarget | null;
  onClose: () => void;
}) => {
  const exists = target !== null && target.state.kind !== 'none';
  const detail = useCalcRuleDetail(exists ? target.need.rule_key : null);
  return (
    <Dialog
      open={target !== null}
      onClose={onClose}
      title={target ? TITLES[target.state.kind] : ''}
      description={target?.need.title}
      size="lg"
    >
      {target &&
        (exists && detail.isError ? (
          <ErrorState title="Правило не загрузилось" onRetry={() => void detail.refetch()} />
        ) : exists && !detail.data ? (
          <SkeletonRows rows={4} />
        ) : (
          <DecisionForm
            key={target.need.rule_key}
            target={target}
            base={detail.data?.versions.find(
              (item) =>
                item.version ===
                (target.state.kind === 'draft' ||
                target.state.kind === 'approved' ||
                target.state.kind === 'closed'
                  ? target.state.version
                  : -1),
            )}
            onClose={onClose}
          />
        ))}
    </Dialog>
  );
};

const DecisionForm = ({
  target,
  base,
  onClose,
}: {
  target: IRuleDecisionTarget;
  base: CalcRuleVersionRead | undefined;
  onClose: () => void;
}) => {
  const { need, state } = target;
  const baseId = useId();
  const types = offeredTypes(need);
  const prefill = sourcePrefill(base);
  const initialType =
    types.find((item) => item === base?.rule_type) ?? types[0] ?? need.rule_types[0];
  const [ruleType, setRuleType] = useState<CalcRuleType | undefined>(initialType);
  const kinds = ruleType ? SOURCE_KINDS[ruleType] : [];
  const [sourceKind, setSourceKind] = useState<SourceKind | undefined>(
    prefill && kinds.includes(prefill.kind) ? prefill.kind : kinds[0],
  );
  const [source, setSource] = useState<Record<string, string>>(prefill?.values ?? {});
  const [parameters, setParameters] = useState<Record<string, string>>(parameterValues(base));
  const [limitations, setLimitations] = useState(
    (base?.content.applicability.limitations ?? []).slice(1).join('\n'),
  );
  const [impact, setImpact] = useState(base?.content.impact ?? '');
  const [changeReason, setChangeReason] = useState('');
  const [problem, setProblem] = useState<string | null>(null);
  const mutation = useSaveRuleDecision();
  const needsReason = state.kind === 'approved' || state.kind === 'closed';

  if (!ruleType || !sourceKind) {
    return (
      <p className="text-sm text-muted">
        Допустимые типы этой заявки (
        {need.rule_types.map((item) => RULE_TYPE_TITLES[item]).join(', ')}) оформляются через API
        реестра правил: форма не собирает данные производителя.
      </p>
    );
  }

  const chooseType = (next: CalcRuleType) => {
    setRuleType(next);
    const allowed = SOURCE_KINDS[next];
    if (!allowed.includes(sourceKind) && allowed[0]) setSourceKind(allowed[0]);
  };

  const submit = () => {
    const body = buildDecision(
      need,
      { ruleType, parameters, sourceKind, source, limitations, impact, changeReason },
      needsReason,
    );
    if (typeof body === 'string') return setProblem(body);
    setProblem(null);
    mutation.mutate({ ruleKey: need.rule_key, body }, { onSuccess: onClose });
  };

  return (
    <div className="flex flex-col gap-[var(--s-4)]">
      <div className="flex flex-col gap-[var(--s-1)] text-sm">
        <span className="font-mono text-xs text-muted">
          {need.rule_key} · {need.systems.join(', ')}
        </span>
        <span>Формула: {need.formula}</span>
        <span className="text-muted">Без решения не определяется: {need.blocks}.</span>
        <span className="text-xs text-muted">
          Пример арифметики (синтетика, не норма): {need.example}
        </span>
      </div>

      <label htmlFor={`${baseId}-type`} className="flex flex-col gap-[var(--s-2)]">
        <span className="text-sm">Тип правила</span>
        <select
          id={`${baseId}-type`}
          value={ruleType}
          onChange={(event) => {
            const next = types.find((item) => item === event.target.value);
            if (next) chooseType(next);
          }}
          className={FIELD}
        >
          {types.map((item) => (
            <option key={item} value={item}>
              {RULE_TYPE_TITLES[item]}
            </option>
          ))}
        </select>
      </label>

      {need.parameters.map((term) => {
        const unit = unitTitle(term.unit);
        return (
          <label
            key={term.name}
            htmlFor={`${baseId}-${term.name}`}
            className="flex flex-col gap-[var(--s-2)]"
          >
            <span className="text-sm">
              {term.meaning}
              {unit && `, ${unit}`}
            </span>
            <input
              id={`${baseId}-${term.name}`}
              inputMode="decimal"
              maxLength={40}
              value={parameters[term.name] ?? ''}
              onChange={(event) =>
                setParameters({ ...parameters, [term.name]: event.target.value })
              }
              className={FIELD}
            />
          </label>
        );
      })}

      <RuleSourceFields
        baseId={`${baseId}-source`}
        kinds={kinds}
        kind={sourceKind}
        values={source}
        onKind={setSourceKind}
        onValue={(key, value) => setSource({ ...source, [key]: value })}
      />

      <label htmlFor={`${baseId}-limits`} className="flex flex-col gap-[var(--s-2)]">
        <span className="text-sm">
          Ограничения применения — по одному в строке
          <span className="text-muted"> — необязательно</span>
        </span>
        <textarea
          id={`${baseId}-limits`}
          rows={2}
          value={limitations}
          onChange={(event) => setLimitations(event.target.value)}
          className={TEXTAREA}
        />
      </label>

      {ruleType === 'TENDER_ASSUMPTION' && (
        <label htmlFor={`${baseId}-impact`} className="flex flex-col gap-[var(--s-2)]">
          <span className="text-sm">Влияние на результат</span>
          <textarea
            id={`${baseId}-impact`}
            rows={2}
            maxLength={2000}
            value={impact}
            onChange={(event) => setImpact(event.target.value)}
            className={TEXTAREA}
          />
        </label>
      )}

      {needsReason && (
        <label htmlFor={`${baseId}-reason`} className="flex flex-col gap-[var(--s-2)]">
          <span className="text-sm">Почему нужна новая версия</span>
          <textarea
            id={`${baseId}-reason`}
            rows={2}
            maxLength={2000}
            value={changeReason}
            onChange={(event) => setChangeReason(event.target.value)}
            className={TEXTAREA}
          />
        </label>
      )}

      <p className="text-xs text-muted">
        Сохраняется черновик. В расчёт он пойдёт после утверждения другим человеком с правом
        проверки.
      </p>
      {problem && <p className="text-sm text-danger">{problem}</p>}
      {mutation.isError && (
        <ErrorState
          title="Решение не записано"
          code={extractCode(mutation.error)}
          description={errorMessage(extractCode(mutation.error), extractMessage(mutation.error))}
        />
      )}
      <DialogActions>
        <Button onClick={onClose} disabled={mutation.isPending}>
          Отмена
        </Button>
        <Button
          variant="primary"
          onClick={submit}
          disabled={mutation.isPending}
          loading={mutation.isPending}
          loadingLabel="Записываем…"
        >
          Сохранить черновик
        </Button>
      </DialogActions>
    </div>
  );
};
