'use client';

import type { DocAnswerOut, DocCandidateOut, DocQuestionOut } from '@quantor/api-client';
import Link from 'next/link';
import { useId, useState, type FC } from 'react';

import { Button, StatusBadge, cx } from '@/components/ui';
import { IconChevronRight } from '@/components/ui/icons';
import {
  useRejectDocCandidate,
  useRemoveDocAnswer,
  useSaveDocAnswer,
} from '@/lib/consistency/doc-question-queries';
import {
  acceptCandidateBody,
  answerValueText,
  docPageHref,
  normAssumptionBody,
  pageText,
  scopeText,
  sourceLabel,
  type DocAnswerBody,
} from '@/lib/consistency/doc-questions';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

import { DocAnswerForm, type DocAnswerMode } from './DocAnswerForm';
import { DocQuestionDetails } from './DocQuestionDetails';

/**
 * Строка вопроса: сам вопрос, главный ответ (подтверждённый, иначе лучший кандидат, иначе
 * «не найдено» с нормативом) и действия. Остальное — в раскрытии под строкой.
 */

interface IRowProps {
  readonly projectId: string;
  readonly question: DocQuestionOut;
}

const failure = (error: unknown): string =>
  extractMessage(error) ?? errorMessage(extractCode(error));

const CELL = 'px-[var(--s-4)] py-[var(--s-3)] align-top max-md:p-0';
const PLACE = 'text-xs text-muted [overflow-wrap:anywhere]';

interface IPlaceProps {
  readonly projectId: string;
  readonly fileName: string | null;
  readonly pageIndex: number | null;
  readonly pageLabel: string | null;
  readonly revisionId: string | null;
}

/** «файл, стр. · Открыть лист»; ссылка — только если известны ревизия и страница. */
const PlaceLine: FC<IPlaceProps> = ({ projectId, fileName, pageIndex, pageLabel, revisionId }) => {
  if (!fileName) return null;
  return (
    <p className={PLACE}>
      {fileName}
      {pageIndex !== null && `, ${pageText(pageIndex, pageLabel)}`}
      {revisionId !== null && pageIndex !== null && (
        <>
          {' · '}
          <Link
            href={docPageHref(projectId, revisionId, pageIndex)}
            className="text-accent underline"
          >
            Открыть лист
          </Link>
        </>
      )}
    </p>
  );
};

interface IAnswerCellProps {
  readonly projectId: string;
  readonly question: DocQuestionOut;
  readonly best: DocCandidateOut | undefined;
  readonly aliveCount: number;
}

const AnswerCell: FC<IAnswerCellProps> = ({ projectId, question, best, aliveCount }) => {
  const confirmed: DocAnswerOut | undefined = question.answers[0];
  const { assumption } = question;

  if (confirmed) {
    const more = question.answers.length - 1;
    return (
      <div className="flex flex-col gap-[var(--s-2)]">
        <div className="flex flex-wrap items-center gap-[var(--s-3)]">
          <span className="text-base font-medium [overflow-wrap:anywhere]">
            {answerValueText(confirmed)}
          </span>
          <StatusBadge tone={confirmed.source === 'document' ? 'success' : 'neutral'}>
            {sourceLabel(confirmed.source)}
          </StatusBadge>
          {more > 0 && <span className="text-xs text-muted">+ ещё {more}</span>}
        </div>
        <p className="text-xs text-muted [overflow-wrap:anywhere]">
          Область: {scopeText(confirmed.scope_building, confirmed.scope_section)}
        </p>
        <PlaceLine
          projectId={projectId}
          fileName={confirmed.file_name}
          pageIndex={confirmed.page_index}
          pageLabel={null}
          revisionId={confirmed.revision_id}
        />
      </div>
    );
  }

  if (best) {
    const more = aliveCount - 1;
    return (
      <div className="flex flex-col gap-[var(--s-2)]">
        <span className="text-base font-medium [overflow-wrap:anywhere]">
          {best.value.display || best.value_text}
        </span>
        <blockquote className="line-clamp-2 text-sm text-muted [overflow-wrap:anywhere]">
          {best.quote}
        </blockquote>
        <PlaceLine
          projectId={projectId}
          fileName={best.file_name}
          pageIndex={best.page_index}
          pageLabel={best.page_label}
          revisionId={best.revision_id}
        />
        {more > 0 && <p className="text-xs text-muted">Других вариантов: {more}</p>}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-[var(--s-2)]">
      <p className="text-sm text-muted">В документации не найдено</p>
      {assumption && (
        <p className="text-xs text-muted">
          Норматив: {assumption.mm_from}
          {assumption.mm_to !== null && `–${assumption.mm_to}`} мм (допущение)
        </p>
      )}
    </div>
  );
};

export const DocQuestionRow: FC<IRowProps> = ({ projectId, question }) => {
  const save = useSaveDocAnswer(projectId);
  const reject = useRejectDocCandidate(projectId);
  const remove = useRemoveDocAnswer(projectId);
  const [open, setOpen] = useState(false);
  const [confirming, setConfirming] = useState(false);
  const [formMode, setFormMode] = useState<DocAnswerMode | null>(null);
  const detailsId = useId();

  const alive = question.candidates
    .filter((candidate) => candidate.status !== 'rejected')
    .sort((left, right) => right.score - left.score);
  const rejected = question.candidates.filter((candidate) => candidate.status === 'rejected');
  const best = alive[0];
  const confirmed = question.answers[0];
  const { assumption } = question;
  const busy = save.isPending || reject.isPending || remove.isPending;

  const submit = (body: DocAnswerBody, done?: () => void) =>
    save.mutate({ code: question.code, body }, { onSuccess: done });

  /** Повторный клик по активной кнопке закрывает форму. */
  const toggleForm = (mode: DocAnswerMode) =>
    setFormMode((current) => (current === mode ? null : mode));

  const errors = [save, reject, remove].filter((mutation) => mutation.isError);

  return (
    <tbody className="border-b border-border last:border-b-0 max-md:block">
      <tr
        data-testid="doc-question"
        className="max-md:flex max-md:flex-col max-md:gap-[var(--s-3)] max-md:px-[var(--s-5)] max-md:py-[var(--s-4)]"
      >
        <td className={CELL}>
          <div className="flex items-start gap-[var(--s-2)]">
            <Button
              variant="ghost"
              compact
              iconOnly
              aria-label={`Подробнее: ${question.title}`}
              aria-expanded={open}
              aria-controls={detailsId}
              onClick={() => setOpen((value) => !value)}
            >
              <IconChevronRight
                width={16}
                height={16}
                className={cx('transition-transform duration-150', open && 'rotate-90')}
              />
            </Button>
            <div className="flex min-w-0 flex-col gap-[var(--s-1)] pt-[var(--s-2)]">
              <span className="text-sm font-medium [overflow-wrap:anywhere]">{question.title}</span>
              <span className="text-xs text-muted [overflow-wrap:anywhere]">
                {question.receiver_param}
              </span>
            </div>
          </div>
        </td>
        <td className={CELL}>
          <AnswerCell
            projectId={projectId}
            question={question}
            best={best}
            aliveCount={alive.length}
          />
        </td>
        <td className={CELL}>
          <div className="flex flex-wrap items-center gap-[var(--s-3)]">
            {confirmed ? (
              <>
                <StatusBadge tone="success">Подтверждено</StatusBadge>
                {confirming ? (
                  <>
                    <Button
                      variant="danger"
                      loading={remove.isPending}
                      aria-label="Подтвердить удаление ответа"
                      onClick={() =>
                        remove.mutate(confirmed.id, { onSuccess: () => setConfirming(false) })
                      }
                    >
                      Да, удалить
                    </Button>
                    <Button onClick={() => setConfirming(false)} disabled={remove.isPending}>
                      Отмена
                    </Button>
                  </>
                ) : (
                  <Button variant="danger" onClick={() => setConfirming(true)}>
                    Удалить
                  </Button>
                )}
              </>
            ) : best ? (
              <>
                <Button
                  variant="primary"
                  disabled={busy}
                  onClick={() => submit(acceptCandidateBody(best.id))}
                >
                  Принять
                </Button>
                <Button disabled={busy} onClick={() => reject.mutate(best.id)}>
                  Отклонить
                </Button>
              </>
            ) : (
              assumption && (
                <Button disabled={busy} onClick={() => submit(normAssumptionBody())}>
                  Принять норматив
                </Button>
              )
            )}
            {!confirmed && (
              <>
                <Button
                  disabled={busy}
                  aria-pressed={formMode === 'manual'}
                  onClick={() => toggleForm('manual')}
                >
                  Ввести вручную
                </Button>
                <Button
                  disabled={busy}
                  aria-pressed={formMode === 'absent'}
                  onClick={() => toggleForm('absent')}
                >
                  Нет в проекте
                </Button>
              </>
            )}
          </div>
        </td>
      </tr>
      {errors.length > 0 && (
        <tr className="max-md:block max-md:px-[var(--s-5)] max-md:pb-[var(--s-4)]">
          <td colSpan={3} className="px-[var(--s-4)] pb-[var(--s-3)] max-md:block max-md:p-0">
            {errors.map((mutation, index) => (
              <p key={index} role="alert" className="text-sm text-danger [overflow-wrap:anywhere]">
                {failure(mutation.error)}
              </p>
            ))}
          </td>
        </tr>
      )}
      {formMode !== null && (
        <tr className="max-md:block max-md:px-[var(--s-5)] max-md:pb-[var(--s-4)]">
          <td colSpan={3} className="px-[var(--s-4)] pb-[var(--s-4)] max-md:block max-md:p-0">
            <DocAnswerForm
              key={formMode}
              question={question}
              mode={formMode}
              pending={save.isPending}
              onSubmit={submit}
              onClose={() => setFormMode(null)}
            />
          </td>
        </tr>
      )}
      {open && (
        <tr id={detailsId} className="max-md:block max-md:px-[var(--s-5)] max-md:pb-[var(--s-4)]">
          <td colSpan={3} className="px-[var(--s-4)] pb-[var(--s-4)] max-md:block max-md:p-0">
            <DocQuestionDetails
              projectId={projectId}
              question={question}
              alive={alive}
              rejected={rejected}
              busy={busy}
              removing={remove.isPending}
              onAccept={(id) => submit(acceptCandidateBody(id))}
              onReject={(id) => reject.mutate(id)}
              onRemove={(id) => remove.mutate(id)}
              onAcceptNorm={() => submit(normAssumptionBody())}
            />
          </td>
        </tr>
      )}
    </tbody>
  );
};
