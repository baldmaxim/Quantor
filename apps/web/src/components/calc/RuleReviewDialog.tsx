'use client';

import { useId, useState } from 'react';

import { TEXTAREA } from '@/components/calc/RuleSourceFields';
import { Button, Dialog, DialogActions, ErrorState, SkeletonRows } from '@/components/ui';
import { unitTitle } from '@/lib/calc/format';
import { RULE_TYPE_TITLES } from '@/lib/calc/rules';
import { sourceLine } from '@/lib/calc/rule-needs';
import { useApproveRule, useCalcRuleDetail, useRejectRule } from '@/lib/calc/rule-needs-queries';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

/**
 * Проверка черновика правила вторым человеком: что именно утверждается — значения, основание,
 * ограничения — и решение с комментарием. Автор и последний редактор не утверждают: сервер
 * откажет, поэтому кнопки у них нет.
 */

export interface IRuleReviewTarget {
  ruleKey: string;
  version: number;
}

export const RuleReviewDialog = ({
  target,
  currentUserId,
  onClose,
}: {
  target: IRuleReviewTarget | null;
  currentUserId: string | undefined;
  onClose: () => void;
}) => {
  const detail = useCalcRuleDetail(target?.ruleKey ?? null);
  const version = detail.data?.versions.find((item) => item.version === target?.version);
  return (
    <Dialog
      open={target !== null}
      onClose={onClose}
      title="Проверка правила"
      description={version ? `${version.content.title} · версия ${version.version}` : undefined}
      size="lg"
    >
      {target &&
        (detail.isError ? (
          <ErrorState title="Правило не загрузилось" onRetry={() => void detail.refetch()} />
        ) : !version ? (
          <SkeletonRows rows={4} />
        ) : (
          <ReviewForm
            key={`${target.ruleKey}@${target.version}`}
            target={target}
            version={version}
            own={
              currentUserId !== undefined &&
              (version.created_by === currentUserId || version.edited_by === currentUserId)
            }
            onClose={onClose}
          />
        ))}
    </Dialog>
  );
};

type Version = NonNullable<ReturnType<typeof useCalcRuleDetail>['data']>['versions'][number];

const ReviewForm = ({
  target,
  version,
  own,
  onClose,
}: {
  target: IRuleReviewTarget;
  version: Version;
  own: boolean;
  onClose: () => void;
}) => {
  const commentId = useId();
  const [comment, setComment] = useState('');
  const approve = useApproveRule();
  const reject = useRejectRule();
  const failed = approve.error ?? reject.error;
  const pending = approve.isPending || reject.isPending;
  const ready = comment.trim().length >= 3;
  const { content } = version;
  const decide = (mutation: typeof approve) =>
    mutation.mutate(
      { ruleKey: target.ruleKey, version: target.version, comment: comment.trim() },
      { onSuccess: onClose },
    );

  return (
    <div className="flex flex-col gap-[var(--s-4)] text-sm">
      <dl className="grid grid-cols-1 gap-x-[var(--s-5)] gap-y-[var(--s-2)] md:grid-cols-[180px_1fr]">
        <dt className="text-muted">Тип</dt>
        <dd>{RULE_TYPE_TITLES[version.rule_type]}</dd>
        <dt className="text-muted">Системы</dt>
        <dd>{content.applicability.systems.join(', ')}</dd>
        <dt className="text-muted">Формула</dt>
        <dd className="wrap-anywhere">{content.formula}</dd>
        {(content.parameters ?? []).map((item) => (
          <div key={item.name} className="contents">
            <dt className="text-muted wrap-anywhere">{item.description}</dt>
            <dd className="font-mono">
              {item.value.replace('.', ',')} {unitTitle(item.unit)}
            </dd>
          </div>
        ))}
        <dt className="text-muted">Основание</dt>
        <dd className="flex flex-col gap-[var(--s-1)] wrap-anywhere">
          {(content.sources ?? []).map((source, index) => (
            <span key={index}>{sourceLine(source)}</span>
          ))}
        </dd>
        <dt className="text-muted">Ограничения</dt>
        <dd className="flex flex-col gap-[var(--s-1)] wrap-anywhere">
          {(content.applicability.limitations ?? []).map((line) => (
            <span key={line}>{line}</span>
          ))}
        </dd>
        {content.impact && (
          <>
            <dt className="text-muted">Влияние</dt>
            <dd className="wrap-anywhere">{content.impact}</dd>
          </>
        )}
        {version.change_reason && (
          <>
            <dt className="text-muted">Причина версии</dt>
            <dd className="wrap-anywhere">{version.change_reason}</dd>
          </>
        )}
      </dl>

      {own && (
        <p className="text-sm text-warning">
          Вы автор или последний редактор этой версии: утверждает другой человек. Отклонить черновик
          можно.
        </p>
      )}

      <label htmlFor={commentId} className="flex flex-col gap-[var(--s-2)]">
        <span>Комментарий: что проверено и по какому документу</span>
        <textarea
          id={commentId}
          rows={2}
          maxLength={2000}
          value={comment}
          onChange={(event) => setComment(event.target.value)}
          className={TEXTAREA}
        />
      </label>
      {failed && (
        <ErrorState
          title="Решение не записано"
          code={extractCode(failed)}
          description={errorMessage(extractCode(failed), extractMessage(failed))}
        />
      )}
      <DialogActions>
        <Button onClick={onClose} disabled={pending}>
          Отмена
        </Button>
        <Button onClick={() => decide(reject)} disabled={!ready || pending}>
          Отклонить
        </Button>
        {!own && (
          <Button
            variant="primary"
            onClick={() => decide(approve)}
            disabled={!ready || pending}
            loading={approve.isPending}
            loadingLabel="Утверждаем…"
          >
            Утвердить
          </Button>
        )}
      </DialogActions>
    </div>
  );
};
