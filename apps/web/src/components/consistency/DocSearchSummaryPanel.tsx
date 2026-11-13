'use client';

import type { DocQuestionsOut, DocSearchSummary } from '@quantor/api-client';
import type { FC } from 'react';

import { Button, ProgressRow, StatusBadge, type BadgeTone } from '@/components/ui';
import { isSearchActive, useStartDocSearch } from '@/lib/consistency/doc-question-queries';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

/**
 * Шапка «Вопросов к документации»: запуск поиска и итог последнего задания.
 *
 * Итог приходит вместе с вопросами, поэтому после перезагрузки страницы ход и результат видны.
 * Числа, которых в итоге нет, показываются прочерком, а не нулём.
 */

interface IPanelProps {
  readonly projectId: string;
  readonly data: DocQuestionsOut;
}

interface IView {
  readonly tone: BadgeTone;
  readonly label: string;
}

const FAILED_VIEW: IView = { tone: 'danger', label: 'ошибка' };
const VIEWS: Readonly<Record<string, IView>> = {
  queued: { tone: 'neutral', label: 'в очереди' },
  running: { tone: 'accent', label: 'идёт поиск' },
  succeeded: { tone: 'success', label: 'готово' },
};

const num = (value: number | null | undefined): string => (value == null ? '—' : String(value));

const FileList: FC<{
  readonly title: string;
  readonly files: readonly string[];
  readonly count: number | null;
  readonly hint?: string;
}> = ({ title, files, count, hint }) => {
  const shown = count ?? files.length;
  if (shown === 0 && files.length === 0) {
    return <p>{`${title}: 0`}</p>;
  }
  return (
    <>
      <details>
        <summary className="min-h-[44px] cursor-pointer py-[var(--s-3)]">
          {title}: {shown}
        </summary>
        <ul className="flex flex-col gap-[var(--s-1)] pb-[var(--s-3)] text-xs text-muted">
          {files.map((name) => (
            <li key={name} className="[overflow-wrap:anywhere]">
              {name}
            </li>
          ))}
        </ul>
      </details>
      {hint ? <p className="text-xs text-muted">{hint}</p> : null}
    </>
  );
};

const Result: FC<{ readonly summary: DocSearchSummary; readonly total: number }> = ({
  summary,
  total,
}) => (
  <div className="flex flex-col gap-[var(--s-1)] text-sm" data-testid="search-result">
    <p>
      Ответ найден у вопросов: {num(summary.questions_found)} из {total}; кандидатов:{' '}
      {num(summary.candidates)}
    </p>
    <p>
      Просмотрено ревизий: {num(summary.revisions_scanned)} из {num(summary.revisions_total)}
    </p>
    <FileList
      title="Текст не извлечён"
      files={summary.no_text_files}
      count={summary.revisions_no_text}
      hint="Нажмите «Разобрать листы» на вкладке «Листы комплекта», затем повторите поиск."
    />
    <FileList
      title="Не читается"
      files={summary.unreadable_files}
      count={summary.revisions_unreadable}
    />
  </div>
);

export const DocSearchSummaryPanel: FC<IPanelProps> = ({ projectId, data }) => {
  const start = useStartDocSearch(projectId);
  const summary = data.last_search;
  const active = isSearchActive(data);
  const view = summary ? (VIEWS[summary.status] ?? FAILED_VIEW) : null;

  return (
    <section
      aria-label="Поиск ответов"
      className="flex flex-col gap-[var(--s-4)] rounded-[var(--radius-md)] border border-border-strong bg-surface px-[var(--s-5)] py-[var(--s-4)]"
    >
      <div className="flex flex-wrap items-center gap-[var(--s-4)]">
        <Button
          variant="primary"
          loading={start.isPending}
          disabled={active}
          onClick={() => start.mutate()}
        >
          Искать ответы
        </Button>
        {view && <StatusBadge tone={view.tone}>{view.label}</StatusBadge>}
        <p className="min-w-0 flex-1 basis-[14rem] text-xs text-muted">
          Поиск по текстовому слою PDF проекта. Найденное — кандидаты: в работу идёт то, что
          подтвердил человек.
        </p>
      </div>
      {active && <ProgressRow value={summary?.progress ?? null} label="Поиск ответов" />}
      {summary?.status === 'failed' && (
        <p role="alert" className="text-sm text-danger">
          {errorMessage(summary.error_code ?? '')}
        </p>
      )}
      {summary?.status === 'succeeded' && (
        <Result summary={summary} total={data.questions.length} />
      )}
      {start.isError && (
        <p role="alert" className="text-sm text-danger">
          {extractMessage(start.error) ?? errorMessage(extractCode(start.error))}
        </p>
      )}
    </section>
  );
};
