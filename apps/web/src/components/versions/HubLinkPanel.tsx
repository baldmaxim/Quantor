'use client';

import type { TenderVersionRead } from '@quantor/api-client';
import { useState } from 'react';

import { Button, ErrorState, Skeleton } from '@/components/ui';
import { errorMessage, extractCode } from '@/lib/errors';
import { formatDeadline, useHubCandidates, useUpdateTenderVersion } from '@/lib/tender-versions';

/**
 * Связь версии со строкой HUBTender.
 *
 * Портал только читает HUBTender: связь записывает номер версии той стороны, но не создаёт
 * и не меняет там ничего. Кандидаты — строки того же номера тендера; сервер сам сверяет
 * номер и берёт номер версии из ответа HUBTender, а не из запроса.
 *
 * У ручного проекта связи нет: его номер никто не подтверждал.
 */

interface IHubLinkPanelProps {
  projectId: string;
  version: TenderVersionRead;
  /** Проект подтянут из HUBTender (а не заведён вручную). */
  projectLinked: boolean;
}

export const HubLinkPanel = ({ projectId, version, projectLinked }: IHubLinkPanelProps) => {
  const editable = version.status === 'draft';
  const candidates = useHubCandidates(projectId, editable && projectLinked);
  const update = useUpdateTenderVersion(projectId, version.id);
  const [picked, setPicked] = useState('');

  const linked = version.external_tender_id;
  const summary = linked
    ? `HUBTender: версия ${version.external_version ?? '—'} · ${linked.slice(0, 8)}…`
    : 'Не связана со строкой HUBTender.';

  const body = (() => {
    if (!editable) return <p className="text-sm">{summary}</p>;
    if (!projectLinked) {
      return (
        <p className="text-sm text-muted">
          Проект заведён вручную — связь с HUBTender недоступна: его номер тендера никто не
          подтверждал.
        </p>
      );
    }
    if (candidates.isPending) return <Skeleton className="h-[44px] w-full" />;
    if (candidates.isError) {
      return (
        <ErrorState
          title="HUBTender не ответил"
          description={errorMessage(extractCode(candidates.error))}
          onRetry={() => void candidates.refetch()}
        />
      );
    }

    const rows = candidates.data;
    return (
      <div className="flex flex-col gap-[var(--s-3)]">
        <p className="text-sm">{summary}</p>
        {rows.length === 0 ? (
          <p className="text-sm text-muted">
            Строк HUBTender с номером этого тендера не найдено: интеграция выключена или версия в
            архиве.
          </p>
        ) : (
          <div className="flex flex-wrap items-end gap-[var(--s-4)]">
            <label className="flex min-w-0 flex-1 basis-[240px] flex-col gap-[var(--s-1)] text-xs text-muted">
              Строка HUBTender
              <select
                value={picked}
                disabled={update.isPending}
                onChange={(event) => setPicked(event.target.value)}
                className="h-[var(--h-ctl)] max-md:h-[44px] rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:text-sm"
              >
                <option value="">— выберите —</option>
                {rows.map((row) => (
                  <option key={row.id} value={row.id}>
                    версия {row.version ?? '—'} · подача {formatDeadline(row.submission_deadline)}
                  </option>
                ))}
              </select>
            </label>
            <Button
              variant="primary"
              disabled={picked === ''}
              loading={update.isPending}
              loadingLabel="Связываем…"
              onClick={() =>
                update.mutate({ external_tender_id: picked }, { onSuccess: () => setPicked('') })
              }
            >
              Связать
            </Button>
          </div>
        )}
        {linked && (
          <div>
            <Button
              compact
              disabled={update.isPending}
              onClick={() => update.mutate({ external_tender_id: null })}
            >
              Снять связь
            </Button>
          </div>
        )}
        {update.error && (
          <p role="alert" className="text-sm text-danger">
            {errorMessage(extractCode(update.error))}
          </p>
        )}
      </div>
    );
  })();

  return (
    <section className="flex flex-col gap-[var(--s-3)]">
      <h3 className="text-sm font-medium">Связь с HUBTender</h3>
      {body}
    </section>
  );
};
