'use client';

import type { DocQuestionOut } from '@quantor/api-client';
import type { FC } from 'react';

import { Button } from '@/components/ui';
import {
  useRejectDocCandidate,
  useRemoveDocAnswer,
  useSaveDocAnswer,
} from '@/lib/consistency/doc-question-queries';
import {
  acceptCandidateBody,
  normAssumptionBody,
  type DocAnswerBody,
} from '@/lib/consistency/doc-questions';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

import { DocAnswerForm } from './DocAnswerForm';
import { DocAnswerItem } from './DocAnswerItem';
import { DocCandidateItem } from './DocCandidateItem';

/**
 * Карточка вопроса: подтверждённые ответы, кандидаты поиска, норматив-допущение, ручной ввод.
 *
 * Норматив — допущение каталога, а не ответ проекта: он принимается отдельной кнопкой и
 * подписывается «Норматив (допущение)».
 */

interface ICardProps {
  readonly projectId: string;
  readonly question: DocQuestionOut;
}

const failure = (error: unknown): string =>
  extractMessage(error) ?? errorMessage(extractCode(error));

export const DocQuestionCard: FC<ICardProps> = ({ projectId, question }) => {
  const save = useSaveDocAnswer(projectId);
  const reject = useRejectDocCandidate(projectId);
  const remove = useRemoveDocAnswer(projectId);

  const alive = question.candidates
    .filter((candidate) => candidate.status !== 'rejected')
    .sort((left, right) => right.score - left.score);
  const rejected = question.candidates.filter((candidate) => candidate.status === 'rejected');
  const busy = save.isPending || reject.isPending || remove.isPending;
  const { assumption } = question;

  const submit = (body: DocAnswerBody, done?: () => void) =>
    save.mutate({ code: question.code, body }, { onSuccess: done });

  const errors = [save, reject, remove].filter((mutation) => mutation.isError);

  return (
    <section
      aria-label={question.title}
      data-testid="doc-question"
      className="flex flex-col gap-[var(--s-4)] rounded-[var(--radius-md)] border border-border-strong bg-surface px-[var(--s-5)] py-[var(--s-4)]"
    >
      <header className="flex flex-col gap-[var(--s-1)]">
        <h2 className="text-base font-medium [overflow-wrap:anywhere]">{question.title}</h2>
        <p className="text-xs text-muted [overflow-wrap:anywhere]">{question.receiver_param}</p>
      </header>

      {question.answers.length > 0 && (
        <div className="flex flex-col gap-[var(--s-2)]">
          <h3 className="text-sm font-medium">Подтверждено</h3>
          <ul className="flex flex-col gap-[var(--s-3)]">
            {question.answers.map((answer) => (
              <DocAnswerItem
                key={answer.id}
                projectId={projectId}
                answer={answer}
                removing={remove.isPending}
                onRemove={(id) => remove.mutate(id)}
              />
            ))}
          </ul>
        </div>
      )}

      <div className="flex flex-col gap-[var(--s-2)]">
        <h3 className="text-sm font-medium">Кандидаты из документации</h3>
        {alive.length === 0 ? (
          <p className="text-sm text-muted">В документации не найдено</p>
        ) : (
          <ul className="flex flex-col gap-[var(--s-3)]">
            {alive.map((candidate) => (
              <DocCandidateItem
                key={candidate.id}
                projectId={projectId}
                candidate={candidate}
                busy={busy}
                onAccept={(id) => submit(acceptCandidateBody(id))}
                onReject={(id) => reject.mutate(id)}
              />
            ))}
          </ul>
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
      </div>

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
            <Button disabled={busy} onClick={() => submit(normAssumptionBody())}>
              Принять норматив
            </Button>
          </div>
        </div>
      )}

      <DocAnswerForm question={question} pending={save.isPending} onSubmit={submit} />

      {errors.map((mutation, index) => (
        <p key={index} role="alert" className="text-sm text-danger">
          {failure(mutation.error)}
        </p>
      ))}
    </section>
  );
};
