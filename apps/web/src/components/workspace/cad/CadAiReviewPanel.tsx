'use client';

import {
  readCadAiReviews,
  startCadAiReview,
  type AiReviewRead,
  type AiReviewStart,
} from '@quantor/api-client';
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';

import { cadErrorText } from '@/lib/cad/errors';
import { remarkTypeLabel } from '@/lib/cad/remarks';
import { unwrap } from '@/lib/queries';

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
const vorStatus = {
  found: 'Есть на виде',
  absent_on_view: 'Нет на виде',
  not_applicable: 'Не относится к виду',
  unclear: 'Неясно',
};
const roleLabel = { corrector: 'правщик', verifier: 'проверщик' };

const label = (review: AiReviewRead): string =>
  review.result ? verdict[review.result.report.verdict] : status[review.status];

const isActive = (review: AiReviewRead | undefined): boolean =>
  review?.status === 'queued' || review?.status === 'running';

const buttonClass =
  'min-h-11 min-w-11 rounded-md border border-border px-3 text-sm text-text disabled:opacity-60';

export const CadAiReviewPanel = ({ wallsJobId }: { readonly wallsJobId: string }) => {
  const client = useQueryClient();
  const queryKey = ['cad-ai-review', wallsJobId];
  const query = useQuery({
    queryKey,
    queryFn: async () =>
      unwrap(await readCadAiReviews({ path: { job_id: wallsJobId }, throwOnError: true })),
    retry: false,
    refetchInterval: ({ state }) => (isActive(state.data?.reviews[0]) ? 5000 : false),
  });
  const start = useMutation({
    mutationFn: async (body: AiReviewStart) =>
      unwrap(await startCadAiReview({ path: { job_id: wallsJobId }, body, throwOnError: true })),
    onSuccess: () => client.invalidateQueries({ queryKey }),
  });
  const available = query.data?.available ?? false;
  const reviews = query.data?.reviews ?? [];
  const review = reviews[0];
  if (!available && !review) return null;
  const maxIterations = query.data?.max_iterations ?? 0;
  const used = reviews.length;
  const exhausted = used >= maxIterations;
  const result = review?.result;
  return (
    <section aria-label="ИИ-проверка вида" className="min-w-0 rounded-md border border-border p-3">
      <h3 className="text-sm font-semibold text-text">ИИ-проверка вида</h3>
      <p className="mt-1 text-xs text-muted">
        Круг {Math.min(used, maxIterations)} из {maxIterations}. Находки становятся замечаниями CAD,
        свойства конструкций не меняются.
      </p>
      {available && !isActive(review) && (
        <div className="mt-2 flex flex-wrap gap-2">
          <button
            type="button"
            disabled={start.isPending || exhausted}
            onClick={() => start.mutate({ role: 'corrector' })}
            className={buttonClass}
          >
            ИИ-правка
          </button>
          <button
            type="button"
            disabled={start.isPending || exhausted}
            onClick={() => start.mutate({ role: 'verifier' })}
            className={buttonClass}
          >
            ИИ-проверка
          </button>
        </div>
      )}
      {available && exhausted && !isActive(review) && (
        <p className="mt-1 text-xs text-muted">Лимит кругов исчерпан</p>
      )}
      {start.isError && (
        <p role="alert" className="mt-2 text-xs text-danger [overflow-wrap:anywhere]">
          {cadErrorText(start.error)}
        </p>
      )}
      {review && (
        <p className="mt-1 text-xs text-muted" role="status">
          {label(review)}
        </p>
      )}
      {review?.error_message && <p className="mt-2 text-xs text-danger">{review.error_message}</p>}
      {review && result && (
        <div className="mt-3 space-y-3 text-xs">
          <p className="text-muted">
            {roleLabel[result.role]} · круг {result.iteration} · стр. {result.page_index + 1} PDF ·{' '}
            {result.model}
          </p>
          <h4 className="font-semibold">Находки ({result.report.findings.length})</h4>
          {result.report.findings.length === 0 && <p>Находок нет.</p>}
          {result.report.findings.map((item, index) => (
            <details key={`${index}-${item.type}`} className="min-w-0 border-b border-border pb-2">
              <summary className="min-h-11 cursor-pointer break-words font-medium">
                {priority[item.priority]} · {remarkTypeLabel(item.type)}
              </summary>
              <div className="mt-2 space-y-2 break-words">
                <p>{item.observation}</p>
                <p>
                  <strong>Основание</strong> {item.evidence}
                </p>
                <p>
                  <strong>Исправление</strong> {item.suggested_fix}
                </p>
              </div>
            </details>
          ))}
          <h4 className="font-semibold">Предложения по свойствам ({result.report.props.length})</h4>
          {result.report.props.length === 0 && <p>Предложений нет.</p>}
          <ul className="space-y-2">
            {result.report.props.map((item, index) => (
              <li key={`${index}-${item.construction_id}`} className="break-words">
                <strong>{item.construction_id}</strong>
                {item.material != null && <span> · материал: {item.material}</span>}
                {item.thickness_mm != null && <span> · толщина: {item.thickness_mm} мм</span>}
                {item.height_mm != null && <span> · высота: {item.height_mm} мм</span>}
                {item.count_openings != null && (
                  <span> · учёт проёмов: {item.count_openings ? 'да' : 'нет'}</span>
                )}
                <p className="mt-1 text-muted">{item.evidence}</p>
              </li>
            ))}
          </ul>
          {result.report.vor_check.length > 0 && (
            <>
              <h4 className="font-semibold">Сверка с ВОР ({result.report.vor_check.length})</h4>
              <ul className="space-y-2">
                {result.report.vor_check.map((item, index) => (
                  <li key={`${index}-${item.vor_ref}`} className="break-words">
                    <strong>{item.vor_ref}</strong> {item.name} · {vorStatus[item.status]}
                    {item.note && <p className="mt-1 text-muted">{item.note}</p>}
                  </li>
                ))}
              </ul>
            </>
          )}
          {result.report.limitations.length > 0 && (
            <details>
              <summary className="min-h-11 cursor-pointer">Ограничения проверки</summary>
              <ul className="mt-2 list-disc space-y-1 pl-4">
                {result.report.limitations.map((note, index) => (
                  <li key={index}>{note}</li>
                ))}
              </ul>
            </details>
          )}
          <p className="text-muted">
            Расход: {result.usage.cost_usd != null ? `${result.usage.cost_usd.toFixed(2)} $` : '—'}{' '}
            · {result.usage.duration_ms != null ? `${Math.round(result.usage.duration_ms / 1000)} с` : '—'}
          </p>
        </div>
      )}
    </section>
  );
};
