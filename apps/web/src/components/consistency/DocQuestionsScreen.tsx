'use client';

import type { FC } from 'react';

import { TopBar } from '@/components/shell/TopBar';
import { EmptyState, ErrorState, SkeletonRows } from '@/components/ui';
import { consistencyAccess } from '@/lib/consistency/access';
import { useDocQuestions } from '@/lib/consistency/doc-question-queries';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';
import { useFeatures, useMeta, useProject } from '@/lib/queries';

import { DocQuestionCard } from './DocQuestionCard';
import { DocSearchSummaryPanel } from './DocSearchSummaryPanel';

/**
 * Экран «Вопросы к документации» (ADR-0043, шаг 2, В4). Закрыт флагом `project.consistency`:
 * при выключенном флаге страницы нет, пока мета не пришла — заглушка загрузки.
 */

interface IScreenProps {
  readonly projectId: string;
}

const MAIN = 'min-w-0 flex-1 px-[var(--s-5)] py-[var(--s-6)] md:px-[var(--s-7)]';

export const DocQuestionsScreen: FC<IScreenProps> = ({ projectId }) => {
  const meta = useMeta();
  const access = consistencyAccess(meta.isSuccess, useFeatures());
  const project = useProject(projectId);
  const questions = useDocQuestions(projectId, access === 'open');

  if (access === 'pending') {
    return (
      <main className={MAIN}>
        <SkeletonRows rows={6} />
      </main>
    );
  }

  if (access === 'hidden') {
    return (
      <main className={MAIN}>
        <EmptyState title="Страница не найдена" />
      </main>
    );
  }

  return (
    <>
      <TopBar
        crumbs={[
          { label: 'Проекты', href: '/projects' },
          { label: project.data?.name ?? '…', href: `/projects/${projectId}` },
          { label: 'Вопросы к документации' },
        ]}
      />
      <main className={`${MAIN} md:py-[var(--s-7)]`}>
        <div className="mx-auto flex w-full max-w-[1200px] flex-col gap-[var(--s-5)]">
          <p className="max-w-[80ch] text-sm text-muted">
            Размеры и параметры, которые нужны расчёту и не заданы в чертежах явно. Поиск даёт
            кандидатов с цитатой и страницей — ответом они становятся после подтверждения человеком.
            «Нет в проекте» — это не ноль.
          </p>
          {questions.isPending && <SkeletonRows rows={6} />}
          {questions.isError && (
            <ErrorState
              title="Вопросы не загрузились"
              code={extractCode(questions.error)}
              description={
                extractMessage(questions.error) ?? errorMessage(extractCode(questions.error))
              }
              onRetry={() => void questions.refetch()}
            />
          )}
          {questions.data && (
            <>
              <DocSearchSummaryPanel projectId={projectId} data={questions.data} />
              {questions.data.questions.map((question) => (
                <DocQuestionCard key={question.code} projectId={projectId} question={question} />
              ))}
            </>
          )}
        </div>
      </main>
    </>
  );
};
