'use client';

import type { CadAttemptRead, CadJobRead } from '@quantor/api-client';
import { useRef, useState, type FC } from 'react';

import { Button } from '@/components/ui';
import { cadCodeText, cadErrorText } from '@/lib/cad/errors';
import { pageLabel, togglePage } from '@/lib/cad/format';
import { useCreateCadJob, useRetryCadJob } from '@/lib/cad/queries';

interface ICadJobActionsProps {
  projectId: string;
  revisionId: string;
  job: CadJobRead;
  /** Выбранная попытка; `null` — задание в очереди, попыток ещё нет. */
  attempt: CadAttemptRead | null;
  onJobCreated: (jobId: string) => void;
  /** Повтор принят: показать новую попытку. */
  onRetried: () => void;
}

/** Повтор, запуск по выбранным страницам, причина отказа и оговорки о статусе результата. */
export const CadJobActions: FC<ICadJobActionsProps> = ({
  projectId,
  revisionId,
  job,
  attempt,
  onJobCreated,
  onRetried,
}) => {
  const retry = useRetryCadJob(projectId, revisionId, job.job_id);
  const create = useCreateCadJob(projectId, revisionId);
  const [selected, setSelected] = useState<readonly number[]>([]);
  // Синхронная защита от двойного нажатия: `isPending` обновляется только после рендера, и два
  // быстрых клика успевают отправить два запроса (сервер ответил бы 409 на второй).
  const retrying = useRef(false);
  const creating = useRef(false);

  const handleRetry = () => {
    if (retrying.current || retry.isPending) return;
    retrying.current = true;
    retry.mutate(undefined, {
      onSuccess: onRetried,
      onSettled: () => {
        retrying.current = false;
      },
    });
  };

  const handleCreate = (pages: readonly number[]) => {
    if (creating.current || create.isPending) return;
    creating.current = true;
    create.mutate(
      { pages },
      {
        onSuccess: (created) => onJobCreated(created.job_id),
        onSettled: () => {
          creating.current = false;
        },
      },
    );
  };

  const planned = attempt?.pages?.planned ?? [];
  // Выбор не должен нести страницу, которой нет в плане выбранной попытки.
  const chosen = selected.filter((index) => planned.includes(index));

  return (
    <section className="flex flex-col gap-[var(--s-5)] rounded-[var(--radius-md)] border border-border-strong bg-surface p-[var(--s-6)]">
      <h2 className="text-sm font-medium">Действия</h2>

      {job.status === 'failed' && (
        <div role="alert" className="flex flex-col gap-[var(--s-2)] text-xs">
          {job.error_code && (
            <p>
              <span className="mono text-danger">{job.error_code}</span>
              <span> · {cadCodeText(job.error_code)}</span>
            </p>
          )}
          {job.error_message && (
            <p className="text-muted [overflow-wrap:anywhere]">{job.error_message}</p>
          )}
        </div>
      )}

      {job.known_limitation && (
        <p className="text-xs text-warning [overflow-wrap:anywhere]">{job.known_limitation}</p>
      )}

      <div className="flex flex-col items-start gap-[var(--s-3)]">
        {job.retryable ? (
          <Button
            variant="primary"
            loading={retry.isPending}
            disabled={create.isPending}
            onClick={handleRetry}
          >
            Повторить
          </Button>
        ) : (
          job.retry_blocked_reason && (
            <p className="text-xs text-muted">Повтор недоступен: {job.retry_blocked_reason}</p>
          )
        )}
        {retry.isError && (
          <p role="alert" className="text-xs text-danger">
            {cadErrorText(retry.error)}
          </p>
        )}
      </div>

      <fieldset className="m-0 flex min-w-0 flex-col gap-[var(--s-3)] border-0 p-0">
        <legend className="mb-[var(--s-3)] text-xs text-muted">
          Запустить по выбранным страницам
        </legend>
        {planned.length === 0 ? (
          <p className="text-xs text-muted">
            Плановые страницы появятся после входного контроля PDF.
          </p>
        ) : (
          <div className="flex flex-wrap gap-[var(--s-3)]">
            {planned.map((index) => (
              <label
                key={index}
                className="flex min-h-[44px] cursor-pointer items-center gap-[var(--s-3)] rounded-[var(--radius-sm)] border border-border-control px-[var(--s-5)] text-sm"
              >
                <input
                  type="checkbox"
                  checked={chosen.includes(index)}
                  onChange={() => setSelected(togglePage(chosen, index))}
                  className="h-[18px] w-[18px] accent-accent"
                />
                {pageLabel(index)}
              </label>
            ))}
          </div>
        )}
        <div>
          <Button
            loading={create.isPending}
            disabled={chosen.length === 0 || retry.isPending}
            onClick={() => handleCreate(chosen)}
          >
            Запустить по выбранным страницам
          </Button>
        </div>
        {create.isError && (
          <p role="alert" className="text-xs text-danger">
            {cadErrorText(create.error)}
          </p>
        )}
      </fieldset>

      {job.review_required && (
        <p className="text-xs text-muted">
          Результат — кандидат движка; инженерная приёмка — отдельный шаг, здесь не выполняется.
        </p>
      )}
    </section>
  );
};
