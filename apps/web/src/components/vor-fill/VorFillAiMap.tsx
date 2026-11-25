'use client';

import type { AiVorMapRead, AiVorMapSuggestionRead } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { Button } from '@/components/ui';
import { vorItemTitle } from '@/lib/cad/vor';
import { useCadVorLinks, usePutCadVorLinks, vorErrorText } from '@/lib/cad/vor-queries';
import { OBJECT_KIND_LABELS } from '@/lib/vor-fill/format';
import {
  CONFIDENCE_CLASSES,
  CONFIDENCE_LABELS,
  hasUnlinked,
  planAccept,
} from '@/lib/vor-fill/ai-map';
import { useStartVorAiMap, useVorAiMap } from '@/lib/vor-fill/queries';

/**
 * Предложения Claude: какие позиции ВОР соответствуют каким объектам Quantor. Модель не получает
 * и не возвращает количества; предложение - только кандидат, связь создаётся кнопкой «Принять»
 * существующим запросом связи. «Отклонить» скрывает предложение локально.
 */

interface IProps {
  readonly projectId: string;
}

const HEADING = 'text-micro font-semibold tracking-[0.06em] text-muted uppercase';

const statusText = (state: AiVorMapRead): string | null => {
  if (state.status === 'queued') return 'В очереди';
  if (state.status === 'running') return 'Claude сопоставляет позиции…';
  if (state.status === 'failed') return state.error_message ?? 'Сопоставление завершилось ошибкой';
  if (state.status === 'cancelled') return 'Задание отменено';
  if (state.stale) return 'ВОР изменился после запуска: предложения устарели, запустите заново.';
  if (state.status === 'succeeded') {
    const version = state.prompt_version === null ? '' : `, промт v${state.prompt_version}`;
    return `Готово: ${state.model ?? 'модель'}${version}`;
  }
  return null;
};

export const VorFillAiMap: FC<IProps> = ({ projectId }) => {
  const state = useVorAiMap(projectId, true);
  const links = useCadVorLinks(projectId, true);
  const start = useStartVorAiMap(projectId);
  const put = usePutCadVorLinks(projectId);
  const [rejected, setRejected] = useState<ReadonlySet<string>>(new Set());
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);

  const data = state.data;
  if (!data?.available) return null;

  const active = data.status === 'queued' || data.status === 'running';
  const visible = data.suggestions.filter((row) => !rejected.has(row.item.id));
  const highOpen = visible.filter((row) => row.confidence === 'high' && hasUnlinked(row));

  const accept = async (rows: readonly AiVorMapSuggestionRead[]): Promise<void> => {
    setBusy(true);
    setFailure(null);
    try {
      // Запросы подряд: каждый ЗАМЕНЯЕТ набор строк группы, а набор считан до первого из них.
      for (const step of planAccept(rows, links.data ?? [])) {
        await put.mutateAsync({ groupKey: step.groupKey, itemIds: step.itemIds });
      }
    } catch (error) {
      setFailure(vorErrorText(error));
    } finally {
      setBusy(false);
    }
  };

  const reject = (id: string): void => setRejected((previous) => new Set([...previous, id]));
  const text = statusText(data);

  return (
    <section aria-label="ИИ-сопоставление" className="flex flex-col gap-[var(--s-3)]">
      <h2 className={HEADING}>Сопоставление позиций ВОР (Claude)</h2>
      <p className="max-w-[80ch] text-xs text-muted">
        Модель видит названия позиций и описания объектов, количеств у неё нет. Предложение — только
        кандидат: связь появится после «Принять».
      </p>
      <div className="flex flex-wrap items-center gap-[var(--s-3)]">
        <Button
          variant="primary"
          disabled={active || start.isPending}
          onClick={() => {
            setRejected(new Set());
            start.mutate();
          }}
        >
          Предложить сопоставление (Claude)
        </Button>
        {highOpen.length > 0 && (
          <Button disabled={busy} onClick={() => void accept(highOpen)}>
            Принять все с высокой уверенностью ({highOpen.length})
          </Button>
        )}
        {text !== null && (
          <span
            role={data.status === 'failed' ? 'alert' : 'status'}
            className={data.status === 'failed' ? 'text-xs text-danger' : 'text-xs text-muted'}
          >
            {text}
          </span>
        )}
        {start.isError && (
          <span role="alert" className="text-xs text-danger">
            {vorErrorText(start.error)}
          </span>
        )}
        {failure !== null && (
          <span role="alert" className="text-xs text-danger">
            {failure}
          </span>
        )}
      </div>

      {visible.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-[var(--s-2)] p-0">
          {visible.map((row) => (
            <li
              key={row.item.id}
              className="flex flex-col gap-[var(--s-2)] rounded-[var(--r-2)] border border-border p-[var(--s-3)] text-xs md:flex-row md:items-start md:justify-between"
            >
              <div className="min-w-0 flex-1 [overflow-wrap:anywhere]">
                <span className="text-text">{vorItemTitle(row.item)}</span>
                {row.item.unit && <span className="text-muted"> · {row.item.unit}</span>}
                <ul className="m-0 mt-[var(--s-1)] list-none p-0 text-muted">
                  {row.objects.map((object) => (
                    <li key={object.group_key}>
                      → {OBJECT_KIND_LABELS[object.kind]}: {object.title}
                      {object.linked && <span className="text-success"> · связано</span>}
                    </li>
                  ))}
                </ul>
                <span className="mt-[var(--s-1)] block">
                  <span className={`font-semibold ${CONFIDENCE_CLASSES[row.confidence]}`}>
                    Уверенность: {CONFIDENCE_LABELS[row.confidence]}
                  </span>
                  <span className="text-muted"> — {row.rationale}</span>
                </span>
              </div>
              <div className="flex shrink-0 flex-wrap gap-[var(--s-2)]">
                {hasUnlinked(row) && (
                  <Button disabled={busy} onClick={() => void accept([row])}>
                    Принять
                  </Button>
                )}
                <Button variant="ghost" onClick={() => reject(row.item.id)}>
                  Отклонить
                </Button>
              </div>
            </li>
          ))}
        </ul>
      )}
      {data.status === 'succeeded' && !data.stale && visible.length === 0 && (
        <p className="text-xs text-muted">Предложений нет.</p>
      )}

      {data.unmatched.length > 0 && !data.stale && (
        <details>
          <summary className="min-h-[44px] cursor-pointer text-xs text-muted">
            Объекты Quantor без позиции в ВОР ({data.unmatched.length})
          </summary>
          <ul className="m-0 list-none p-0 text-xs text-muted">
            {data.unmatched.map((row) => (
              <li key={row.object.group_key}>
                {OBJECT_KIND_LABELS[row.object.kind]}: {row.object.title} — {row.reason}
              </li>
            ))}
          </ul>
        </details>
      )}
      {data.limitations.length > 0 && !data.stale && (
        <ul className="m-0 flex list-none flex-col gap-[var(--s-1)] p-0 text-xs text-muted">
          {data.limitations.map((line) => (
            <li key={line}>{line}</li>
          ))}
        </ul>
      )}
    </section>
  );
};
