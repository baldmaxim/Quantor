'use client';

import { useState, type FC } from 'react';

import { DocAnswerForm } from '@/components/consistency/DocAnswerForm';
import { Button, ButtonLink, Dialog } from '@/components/ui';
import { useRejectDocCandidate, useSaveDocAnswer } from '@/lib/consistency/doc-question-queries';
import {
  acceptCandidateBody,
  candidatePlace,
  pageText,
  type DocAnswerBody,
} from '@/lib/consistency/doc-questions';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

import type { AttentionItem, IDocItem } from './attentionQueue';

/**
 * Прямой вопрос человеку: один вопрос за раз, ответ сохраняется сразу.
 *
 * Вопрос к документации: есть кандидат - «Подтвердить?» (подтвердить, другое значение, отклонить
 * кандидата), нет - «Введите значение». Масштаб CAD: только переход к калибровке.
 */

interface IAttentionDialogProps {
  readonly projectId: string;
  readonly open: boolean;
  readonly items: readonly AttentionItem[];
  readonly onClose: () => void;
  readonly onSnooze: (id: string) => void;
}

const failure = (error: unknown): string =>
  extractMessage(error) ?? errorMessage(extractCode(error));

interface IDocQuestionProps {
  readonly projectId: string;
  readonly item: IDocItem;
  readonly onSnooze: () => void;
}

const DocQuestion: FC<IDocQuestionProps> = ({ projectId, item, onSnooze }) => {
  const { question, candidate } = item;
  const save = useSaveDocAnswer(projectId);
  const reject = useRejectDocCandidate(projectId);
  const [manual, setManual] = useState(false);
  const busy = save.isPending || reject.isPending;
  const error = save.error ?? reject.error;

  const submit = (body: DocAnswerBody, done?: () => void) =>
    save.mutate({ code: question.code, body }, { onSuccess: done });

  const place = candidate ? candidatePlace(candidate) : null;
  const showForm = candidate === null || manual;

  return (
    <div className="flex flex-col gap-[var(--s-4)]">
      <p className="text-sm text-muted">{candidate ? 'Подтвердить?' : 'Введите значение'}</p>
      <h3 className="text-base font-medium [overflow-wrap:anywhere]">{question.title}</h3>
      {candidate && (
        <div className="flex flex-col gap-[var(--s-2)] rounded-[var(--radius-sm)] border border-border bg-surface-muted px-[var(--s-4)] py-[var(--s-4)]">
          <span className="text-lg font-medium [overflow-wrap:anywhere]">
            {candidate.value.display || candidate.value_text}
          </span>
          <blockquote className="line-clamp-3 text-sm text-muted [overflow-wrap:anywhere]">
            {candidate.quote}
          </blockquote>
          <p className="text-xs text-muted [overflow-wrap:anywhere]">
            {candidate.file_name}, {pageText(candidate.page_index, candidate.page_label)}
            {place && ` · ${place}`}
          </p>
        </div>
      )}
      {showForm && (
        <DocAnswerForm
          question={question}
          mode="manual"
          pending={save.isPending}
          onSubmit={submit}
          onClose={() => setManual(false)}
        />
      )}
      {(save.isError || reject.isError) && (
        <p role="alert" className="text-sm text-danger">
          {failure(error)}
        </p>
      )}
      <div className="flex flex-wrap gap-[var(--s-3)]">
        {candidate && (
          <Button
            variant="primary"
            loading={save.isPending && !manual}
            disabled={busy}
            onClick={() => submit(acceptCandidateBody(candidate.id))}
          >
            Подтвердить
          </Button>
        )}
        {candidate && !manual && (
          <Button disabled={busy} onClick={() => setManual(true)}>
            Другое значение
          </Button>
        )}
        {candidate && (
          <Button
            variant="danger"
            loading={reject.isPending}
            disabled={busy}
            onClick={() => reject.mutate(candidate.id)}
          >
            Отклонить кандидата
          </Button>
        )}
        <Button disabled={busy} onClick={onSnooze}>
          Позже
        </Button>
      </div>
    </div>
  );
};

export const AttentionDialog: FC<IAttentionDialogProps> = ({
  projectId,
  open,
  items,
  onClose,
  onSnooze,
}) => {
  const current = items[0];
  const rest = items.length - 1;

  return (
    <Dialog
      open={open && current !== undefined}
      onClose={onClose}
      title="Нужен ваш ответ"
      description={rest > 0 ? `Ещё ${rest}` : 'Последний вопрос'}
    >
      {current?.kind === 'doc' && (
        <DocQuestion
          // Состояние формы и ошибок не переходит на следующий вопрос.
          key={current.id}
          projectId={projectId}
          item={current}
          onSnooze={() => onSnooze(current.id)}
        />
      )}
      {current?.kind === 'scale' && (
        <div className="flex flex-col gap-[var(--s-5)]">
          <p className="text-base [overflow-wrap:anywhere]">{current.text}</p>
          <div className="flex flex-wrap gap-[var(--s-3)]">
            <ButtonLink href={current.href} variant="primary" onClick={onClose}>
              Откалибровать
            </ButtonLink>
            <Button onClick={() => onSnooze(current.id)}>Позже</Button>
          </div>
        </div>
      )}
    </Dialog>
  );
};
