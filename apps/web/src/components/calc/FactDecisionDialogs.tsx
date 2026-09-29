'use client';

import type { CalcFactRead, CalcFactTypeRead } from '@quantor/api-client';
import { useId, useState } from 'react';

import { FactEvidence } from '@/components/calc/FactEvidence';
import { Button, Dialog, DialogActions, ErrorState, SkeletonRows, cx } from '@/components/ui';
import {
  useCalcConflicts,
  useDecideConflict,
  useReviewFact,
  useWithdrawFact,
} from '@/lib/calc/fact-actions';
import { SOURCE_CLASS_TITLES, formatSubject, formatValue, unitTitle } from '@/lib/calc/format';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

/**
 * Решения человека по фактам: какой источник прав в конфликте, подтвердить или отклонить
 * утверждение, отозвать своё. Решение не удаляет утверждения — оно записывается с причиной, и
 * при новом утверждении по тому же ключу реестр попросит решить заново.
 */

const TEXTAREA =
  'rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] py-[var(--s-2)] text-base text-text md:text-sm';

const claimText = (claim: CalcFactRead, type: CalcFactTypeRead | undefined): string => {
  const unit = type?.unit_title ?? unitTitle(type?.unit);
  return `${formatValue(claim.value, type)}${unit ? ` ${unit}` : ''}`;
};

/** Расхождение по идентификатору (строка матрицы) или по ключу факта (строка таблицы). */
export type ConflictTarget = { conflictId: string } | { factKey: string };

const ACTIVE = new Set(['OPEN', 'REOPENED']);

export const ConflictDialog = ({
  projectId,
  target,
  canDecide,
  factTypes,
  onClose,
}: {
  projectId: string;
  target: ConflictTarget | null;
  /** Решает проверяющий (calc.verify); остальные видят варианты и их основания. */
  canDecide: boolean;
  factTypes: ReadonlyMap<string, CalcFactTypeRead>;
  onClose: () => void;
}) => {
  const conflicts = useCalcConflicts(projectId, target !== null);
  const conflict = conflicts.data?.find((item) =>
    target && 'conflictId' in target
      ? item.id === target.conflictId
      : item.fact_key === target?.factKey && ACTIVE.has(item.status),
  );
  return (
    <Dialog
      open={target !== null}
      onClose={onClose}
      title={canDecide ? 'Решить расхождение источников' : 'Расхождение источников'}
      size="lg"
    >
      {conflicts.isError ? (
        <ErrorState title="Расхождение не загрузилось" onRetry={() => void conflicts.refetch()} />
      ) : conflicts.isPending ? (
        <SkeletonRows rows={3} />
      ) : !conflict ? (
        <p className="text-sm text-muted">Открытого расхождения нет — его уже решили.</p>
      ) : (
        <ConflictForm
          key={conflict.id}
          projectId={projectId}
          conflictId={conflict.id}
          claims={conflict.claims}
          canDecide={canDecide}
          type={factTypes.get(conflict.fact_type)}
          onClose={onClose}
        />
      )}
    </Dialog>
  );
};

const ConflictForm = ({
  projectId,
  conflictId,
  claims,
  canDecide,
  type,
  onClose,
}: {
  projectId: string;
  conflictId: string;
  claims: CalcFactRead[];
  canDecide: boolean;
  type: CalcFactTypeRead | undefined;
  onClose: () => void;
}) => {
  const reasonId = useId();
  const [chosen, setChosen] = useState<string | null>(null);
  const [reason, setReason] = useState('');
  const mutation = useDecideConflict(projectId);
  const ready = chosen !== null && reason.trim().length >= 3;

  return (
    <div className="flex flex-col gap-[var(--s-4)]">
      <p className="text-sm text-muted">
        {type?.title ?? claims[0]?.fact_type}
        {claims[0] ? ` · ${formatSubject(claims[0].subject)}` : ''}.{' '}
        {canDecide
          ? 'Выберите утверждение, которое верно для объекта; остальные останутся в реестре, но в расчёт не пойдут.'
          : 'Пока расхождение не решено, значение в расчёт не идёт. Решает проверяющий.'}
      </p>
      <ul
        className="flex list-none flex-col gap-[var(--s-3)]"
        role={canDecide ? 'radiogroup' : undefined}
      >
        {claims.map((claim) => {
          const summary = (
            <>
              <span className="font-mono">{claimText(claim, type)}</span>
              <span className="text-xs text-muted wrap-anywhere">
                {SOURCE_CLASS_TITLES[claim.source_class]} · {claim.method}
                {claim.note ? ` · ${claim.note}` : ''}
              </span>
            </>
          );
          return (
            <li key={claim.id} className="flex flex-col gap-[var(--s-2)]">
              {canDecide ? (
                <button
                  type="button"
                  role="radio"
                  aria-checked={chosen === claim.id}
                  onClick={() => setChosen(claim.id)}
                  className={cx(
                    'flex min-h-[44px] w-full flex-col gap-[var(--s-1)] rounded-[var(--radius-sm)] border px-[var(--s-4)] py-[var(--s-2)] text-left text-sm',
                    chosen === claim.id ? 'border-accent bg-accent-soft' : 'border-border',
                  )}
                >
                  {summary}
                </button>
              ) : (
                <div className="flex flex-col gap-[var(--s-1)] rounded-[var(--radius-sm)] border border-border px-[var(--s-4)] py-[var(--s-2)] text-sm">
                  {summary}
                </div>
              )}
              <FactEvidence projectId={projectId} evidence={claim.evidence} />
            </li>
          );
        })}
      </ul>
      {!canDecide && (
        <DialogActions>
          <Button onClick={onClose}>Закрыть</Button>
        </DialogActions>
      )}
      {canDecide && (
        <>
          <label htmlFor={reasonId} className="flex flex-col gap-[var(--s-2)]">
            <span className="text-sm">Причина решения</span>
            <textarea
              id={reasonId}
              rows={2}
              maxLength={1000}
              value={reason}
              onChange={(event) => setReason(event.target.value)}
              className={TEXTAREA}
            />
          </label>
          {mutation.isError && (
            <ErrorState
              title="Решение не записано"
              code={extractCode(mutation.error)}
              description={errorMessage(
                extractCode(mutation.error),
                extractMessage(mutation.error),
              )}
            />
          )}
          <DialogActions>
            <Button onClick={onClose} disabled={mutation.isPending}>
              Отмена
            </Button>
            <Button
              variant="primary"
              disabled={!ready || mutation.isPending}
              loading={mutation.isPending}
              loadingLabel="Записываем…"
              onClick={() =>
                chosen &&
                mutation.mutate(
                  { conflictId, chosenFactId: chosen, reason: reason.trim() },
                  { onSuccess: onClose },
                )
              }
            >
              Принять решение
            </Button>
          </DialogActions>
        </>
      )}
    </div>
  );
};

export type FactAction = 'confirm' | 'reject' | 'withdraw';

const ACTIONS: Readonly<Record<FactAction, { title: string; button: string; needsText: boolean }>> =
  {
    confirm: { title: 'Подтвердить утверждение', button: 'Подтвердить', needsText: false },
    reject: { title: 'Отклонить утверждение', button: 'Отклонить', needsText: true },
    withdraw: { title: 'Отозвать утверждение', button: 'Отозвать', needsText: true },
  };

export const FactActionDialog = ({
  projectId,
  target,
  factTypes,
  onClose,
}: {
  projectId: string;
  target: { action: FactAction; fact: CalcFactRead } | null;
  factTypes: ReadonlyMap<string, CalcFactTypeRead>;
  onClose: () => void;
}) => (
  <Dialog
    open={target !== null}
    onClose={onClose}
    title={target ? ACTIONS[target.action].title : ''}
    description={
      target
        ? `${factTypes.get(target.fact.fact_type)?.title ?? target.fact.fact_type}: ${claimText(target.fact, factTypes.get(target.fact.fact_type))}`
        : undefined
    }
  >
    {target && (
      <FactActionForm
        key={`${target.action}|${target.fact.id}`}
        projectId={projectId}
        action={target.action}
        fact={target.fact}
        onClose={onClose}
      />
    )}
  </Dialog>
);

const FactActionForm = ({
  projectId,
  action,
  fact,
  onClose,
}: {
  projectId: string;
  action: FactAction;
  fact: CalcFactRead;
  onClose: () => void;
}) => {
  const textId = useId();
  const [text, setText] = useState('');
  const review = useReviewFact(projectId);
  const withdraw = useWithdrawFact(projectId);
  const mutation = action === 'withdraw' ? withdraw : review;
  const spec = ACTIONS[action];
  const ready = !spec.needsText || text.trim().length >= 3;
  const submit = () => {
    const comment = text.trim() || null;
    if (action === 'withdraw') {
      withdraw.mutate({ factId: fact.id, reason: text.trim() }, { onSuccess: onClose });
    } else {
      review.mutate(
        { factId: fact.id, status: action === 'confirm' ? 'CONFIRMED' : 'REJECTED', comment },
        { onSuccess: onClose },
      );
    }
  };
  return (
    <div className="flex flex-col gap-[var(--s-4)]">
      <label htmlFor={textId} className="flex flex-col gap-[var(--s-2)]">
        <span className="text-sm">
          {action === 'confirm' ? 'Комментарий — необязательно' : 'Причина'}
        </span>
        <textarea
          id={textId}
          rows={2}
          maxLength={1000}
          value={text}
          onChange={(event) => setText(event.target.value)}
          className={TEXTAREA}
        />
      </label>
      {mutation.isError && (
        <ErrorState
          title="Действие не выполнено"
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
          disabled={!ready || mutation.isPending}
          loading={mutation.isPending}
          onClick={submit}
        >
          {spec.button}
        </Button>
      </DialogActions>
    </div>
  );
};
