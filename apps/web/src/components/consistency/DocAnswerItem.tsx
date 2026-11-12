'use client';

import type { DocAnswerOut } from '@quantor/api-client';
import Link from 'next/link';
import { useState, type FC } from 'react';

import { Button, StatusBadge } from '@/components/ui';
import {
  answerValueText,
  docPageHref,
  pageText,
  scopeText,
  sourceLabel,
} from '@/lib/consistency/doc-questions';
import { formatWhen } from '@/lib/format';

/** Подтверждённый ответ: значение, источник, область, цитата, место в документе, удаление с подтверждением. */

interface IItemProps {
  readonly projectId: string;
  readonly answer: DocAnswerOut;
  readonly removing: boolean;
  readonly onRemove: (answerId: string) => void;
}

export const DocAnswerItem: FC<IItemProps> = ({ projectId, answer, removing, onRemove }) => {
  const [confirming, setConfirming] = useState(false);
  const hasPlace = answer.revision_id !== null && answer.page_index !== null;

  return (
    <li
      data-testid="doc-answer"
      className="flex flex-col gap-[var(--s-2)] rounded-[var(--radius-sm)] border border-border bg-surface-muted px-[var(--s-4)] py-[var(--s-3)]"
    >
      <div className="flex flex-wrap items-center gap-[var(--s-3)]">
        <span className="text-base font-medium [overflow-wrap:anywhere]">
          {answerValueText(answer)}
        </span>
        <StatusBadge tone={answer.source === 'document' ? 'success' : 'neutral'}>
          {sourceLabel(answer.source)}
        </StatusBadge>
      </div>
      <p className="text-xs text-muted">
        Область: {scopeText(answer.scope_building, answer.scope_section)}
      </p>
      {answer.quote && (
        <blockquote className="border-l-2 border-border-strong pl-[var(--s-3)] text-sm text-muted [overflow-wrap:anywhere]">
          {answer.quote}
        </blockquote>
      )}
      {answer.norm_ref && (
        <p className="text-xs text-muted [overflow-wrap:anywhere]">{answer.norm_ref}</p>
      )}
      {answer.file_name && (
        <p className="text-xs text-muted [overflow-wrap:anywhere]">
          {answer.file_name}
          {answer.page_index !== null && `, ${pageText(answer.page_index, null)}`}
          {hasPlace && answer.revision_id && answer.page_index !== null && (
            <>
              {' · '}
              <Link
                href={docPageHref(projectId, answer.revision_id, answer.page_index)}
                className="text-accent underline"
              >
                Открыть лист
              </Link>
            </>
          )}
        </p>
      )}
      {answer.note && <p className="text-sm [overflow-wrap:anywhere]">{answer.note}</p>}
      <p className="text-xs text-muted">
        Подтвердил: пользователь {answer.confirmed_by.slice(0, 8)},{' '}
        {formatWhen(answer.confirmed_at)}
      </p>
      <div className="flex flex-wrap items-center gap-[var(--s-3)]">
        {confirming ? (
          <>
            <span className="text-sm">Удалить ответ?</span>
            <Button
              variant="danger"
              loading={removing}
              onClick={() => onRemove(answer.id)}
              aria-label="Подтвердить удаление ответа"
            >
              Да, удалить
            </Button>
            <Button onClick={() => setConfirming(false)} disabled={removing}>
              Отмена
            </Button>
          </>
        ) : (
          <Button variant="danger" onClick={() => setConfirming(true)}>
            Удалить
          </Button>
        )}
      </div>
    </li>
  );
};
