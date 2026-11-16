'use client';

import {
  readCadOutlineReviews,
  startCadOutlineReview,
  type OutlineReviewRead,
} from '@quantor/api-client';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { cadErrorText } from '@/lib/cad/errors';
import { env } from '@/lib/env';
import { unwrap } from '@/lib/queries';

const sourceLabel = {
  project: 'Проект',
  explanatory_note: 'Пояснительная записка',
  terms_of_reference: 'Техническое задание',
  contract: 'Договор',
};
const priority = { blocking: 'Блокирует', major: 'Существенное', minor: 'Незначительное' };
const verdict = {
  ready_for_human_review: 'Готово к проверке инженером',
  needs_correction: 'Требуются исправления',
  insufficient_evidence: 'Недостаточно данных',
};
const status = {
  queued: 'В очереди',
  running: 'Проверка идёт',
  succeeded: 'Проверка завершена',
  failed: 'Ошибка проверки',
  cancelled: 'Проверка отменена',
};

const label = (review: OutlineReviewRead): string =>
  review.result ? verdict[review.result.report.verdict] : status[review.status];

const isActive = (review: OutlineReviewRead | undefined): boolean =>
  review?.status === 'queued' || review?.status === 'running';

export const CadOutlineReviewPanel = ({ wallsJobId }: { readonly wallsJobId: string }) => {
  const client = useQueryClient();
  const queryKey = ['cad-outline-review', wallsJobId];
  const query = useQuery({
    queryKey,
    queryFn: async () =>
      unwrap(await readCadOutlineReviews({ path: { job_id: wallsJobId }, throwOnError: true })),
    retry: false,
    refetchInterval: ({ state }) => (isActive(state.data?.reviews[0]) ? 5000 : false),
  });
  const start = useMutation({
    mutationFn: async () =>
      unwrap(await startCadOutlineReview({ path: { job_id: wallsJobId }, throwOnError: true })),
    onSuccess: () => client.invalidateQueries({ queryKey }),
  });
  const available = query.data?.available ?? false;
  const review = query.data?.reviews[0];
  if (!available && !review) return null;
  const result = review?.result;
  return (
    <section aria-label="Проверка обводки Codex" className="min-w-0 rounded-md border border-border p-3">
      <h3 className="text-sm font-semibold text-text">Проверка обводки Codex</h3>
      <p className="mt-1 text-xs text-muted">Ручной этап после движка: проверка по SSH, 5–8 минут</p>
      {available && !isActive(review) && (
        <button
          type="button"
          disabled={start.isPending}
          onClick={() => start.mutate()}
          className="mt-2 min-h-11 rounded-md border border-border px-3 text-sm text-text disabled:opacity-60"
        >
          {review ? 'Проверить заново' : 'Запустить проверку'}
        </button>
      )}
      {start.isError && (
        <p role="alert" className="mt-2 text-xs text-danger [overflow-wrap:anywhere]">
          {cadErrorText(start.error)}
        </p>
      )}
      {review && (
        <p className="mt-1 text-xs text-muted" role="status">{label(review)}</p>
      )}
      {review?.error_message && <p className="mt-2 text-xs text-danger">{review.error_message}</p>}
      {review && result && (
        <>
          <p className="mt-1 text-xs text-muted">{result.floor}-й этаж · стр. {result.pdf_page} PDF</p>
          <div className="mt-3 space-y-3 text-xs">
            <h4 className="font-semibold">Замечания ({result.report.findings.length})</h4>
            {result.report.findings.length === 0 && <p>Замечаний нет.</p>}
            {result.report.findings.map((item, index) => (
              <details key={`${index}-${item.location}`} className="min-w-0 border-b border-border pb-2">
                <summary className="cursor-pointer break-words font-medium">
                  {priority[item.priority]} · {item.location}
                </summary>
                <div className="mt-2 space-y-2 break-words">
                  <p>{item.observation}</p>
                  <p><strong>Основание</strong> {item.evidence}</p>
                  <p><strong>Исправление</strong> {item.suggested_fix}</p>
                </div>
              </details>
            ))}
            <h4 className="font-semibold">Источники</h4>
            <ul className="space-y-3">
              {result.report.sources.map((source) => (
                <li key={source.role} className="break-words">
                  <a
                    className="font-medium text-text underline underline-offset-2"
                    href={`${env.apiBaseUrl}/api/v1/jobs/${review.job_id}/cad-outline-source/${source.role}`}
                    target="_blank"
                    rel="noreferrer"
                  >
                    {sourceLabel[source.role]}
                  </a>
                  <p className="mt-1 text-muted">{source.reference}</p>
                  <p className="mt-1">{source.observation}</p>
                </li>
              ))}
            </ul>
            {result.report.limitations.length > 0 && (
              <details>
                <summary className="cursor-pointer">Ограничения проверки</summary>
                <ul className="mt-2 list-disc space-y-1 pl-4">
                  {result.report.limitations.map((note, index) => (
                    <li key={index}>{note}</li>
                  ))}
                </ul>
              </details>
            )}
          </div>
        </>
      )}
    </section>
  );
};
