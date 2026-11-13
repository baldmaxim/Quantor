'use client';

import type { DocCandidateOut, DocQuestionOut } from '@quantor/api-client';
import type { FC } from 'react';

import { Button } from '@/components/ui';

import { DocAnswerItem } from './DocAnswerItem';
import { DocCandidateItem } from './DocCandidateItem';

/**
 * Раскрытая часть строки вопроса: все подтверждённые ответы, живые и отклонённые кандидаты,
 * норматив-допущение. Ручной ввод — в строке вопроса.
 *
 * Норматив — допущение каталога, а не ответ проекта: он принимается отдельной кнопкой.
 */

interface IDetailsProps {
  readonly projectId: string;
  readonly question: DocQuestionOut;
  readonly alive: readonly DocCandidateOut[];
  readonly rejected: readonly DocCandidateOut[];
  readonly busy: boolean;
  readonly removing: boolean;
  readonly onAccept: (candidateId: string) => void;
  readonly onReject: (candidateId: string) => void;
  readonly onRemove: (answerId: string) => void;
  readonly onAcceptNorm: () => void;
}

export const DocQuestionDetails: FC<IDetailsProps> = ({
  projectId,
  question,
  alive,
  rejected,
  busy,
  removing,
  onAccept,
  onReject,
  onRemove,
  onAcceptNorm,
}) => {
  const { assumption } = question;

  return (
    <div className="flex flex-col gap-[var(--s-4)]">
      {question.answers.length > 0 && (
        <div className="flex flex-col gap-[var(--s-2)]">
          <h3 className="text-sm font-medium">Подтверждено</h3>
          <ul className="flex flex-col gap-[var(--s-3)]">
            {question.answers.map((answer) => (
              <DocAnswerItem
                key={answer.id}
                projectId={projectId}
                answer={answer}
                removing={removing}
                onRemove={onRemove}
              />
            ))}
          </ul>
        </div>
      )}

      {alive.length > 0 && (
        <div className="flex flex-col gap-[var(--s-2)]">
          <h3 className="text-sm font-medium">Кандидаты из документации</h3>
          <ul className="flex flex-col gap-[var(--s-3)]">
            {alive.map((candidate) => (
              <DocCandidateItem
                key={candidate.id}
                projectId={projectId}
                candidate={candidate}
                busy={busy}
                onAccept={onAccept}
                onReject={onReject}
              />
            ))}
          </ul>
        </div>
      )}

      {rejected.length > 0 && (
        <details>
          <summary className="min-h-[44px] cursor-pointer py-[var(--s-3)] text-sm text-muted">
            Отклонённые ({rejected.length})
          </summary>
          <ul className="flex flex-col gap-[var(--s-3)]">
            {rejected.map((candidate) => (
              <DocCandidateItem
                key={candidate.id}
                projectId={projectId}
                candidate={candidate}
                busy={busy}
              />
            ))}
          </ul>
        </details>
      )}

      {assumption && (
        <div
          data-testid="doc-assumption"
          className="flex flex-col gap-[var(--s-2)] rounded-[var(--radius-sm)] border border-dashed border-border-strong px-[var(--s-4)] py-[var(--s-3)]"
        >
          <p className="text-sm font-medium">
            Норматив: {assumption.mm_from}
            {assumption.mm_to !== null && `–${assumption.mm_to}`} мм
          </p>
          <p className="text-xs text-muted [overflow-wrap:anywhere]">{assumption.reference}</p>
          {assumption.note && (
            <p className="text-xs text-muted [overflow-wrap:anywhere]">{assumption.note}</p>
          )}
          <p className="text-xs text-warning">Допущение, не ответ проекта</p>
          <div>
            <Button disabled={busy} onClick={onAcceptNorm}>
              Принять норматив
            </Button>
          </div>
        </div>
      )}
    </div>
  );
};
