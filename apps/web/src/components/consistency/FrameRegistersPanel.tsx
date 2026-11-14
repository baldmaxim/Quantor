'use client';

import type { RegisterStatus, SheetRegisterOut, SheetRegistersOut } from '@quantor/api-client';
import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useRef, type FC } from 'react';

import { Button, ProgressRow, StatusBadge, type BadgeTone } from '@/components/ui';
import { frameKeys } from '@/lib/consistency/building-frame-queries';
import {
  isExtractActive,
  useBulkRegisterStatus,
  useSheetRegisters,
  useStartRegisterExtract,
} from '@/lib/consistency/sheet-register-queries';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

/**
 * Ведомости листов (С2, «ведомость ↔ листы»): разбор по тексту страниц PDF, просмотр строк и
 * подтверждение ведомости целиком. В проверки каркаса идёт только подтверждённая ведомость.
 */

interface IPanelProps {
  readonly projectId: string;
}

const STATUS_LABELS: Record<RegisterStatus, string> = {
  candidate: 'Кандидат',
  confirmed: 'Подтверждена',
  rejected: 'Отклонена',
};

const STATUS_TONES: Record<RegisterStatus, BadgeTone> = {
  candidate: 'warning',
  confirmed: 'success',
  rejected: 'neutral',
};

const num = (value: number | null | undefined): string => (value == null ? '—' : String(value));

export const pagesText = (pages: readonly number[]): string =>
  pages.length === 0
    ? '—'
    : pages.length === 1
      ? `стр. ${pages[0]! + 1}`
      : `стр. ${pages[0]! + 1}–${pages[pages.length - 1]! + 1}`;

const RegisterItem: FC<{
  readonly register: SheetRegisterOut;
  readonly busy: boolean;
  readonly onStatus: (id: string, status: RegisterStatus) => void;
}> = ({ register, busy, onStatus }) => (
  <li data-testid="sheet-register" className="flex flex-col gap-[var(--s-2)] py-[var(--s-3)]">
    <div className="flex flex-wrap items-center gap-[var(--s-3)]">
      <StatusBadge tone={STATUS_TONES[register.status]}>
        {STATUS_LABELS[register.status]}
      </StatusBadge>
      <span className="text-sm font-medium [overflow-wrap:anywhere]">{register.file_name}</span>
      <span className="tabular text-xs text-muted">
        {pagesText(register.pages)} · строк: {register.entries.length}
        {register.duplicates.length > 0 && ` · повторы номеров: ${register.duplicates.join(', ')}`}
      </span>
      <div className="ml-auto flex flex-wrap gap-[var(--s-2)] max-sm:ml-0">
        {register.status === 'candidate' ? (
          <>
            <Button
              compact
              variant="primary"
              disabled={busy}
              onClick={() => onStatus(register.id, 'confirmed')}
            >
              Подтвердить
            </Button>
            <Button compact disabled={busy} onClick={() => onStatus(register.id, 'rejected')}>
              Отклонить
            </Button>
          </>
        ) : (
          <Button compact disabled={busy} onClick={() => onStatus(register.id, 'candidate')}>
            Вернуть в кандидаты
          </Button>
        )}
      </div>
    </div>
    <details>
      <summary className="min-h-[44px] cursor-pointer py-[var(--s-2)] text-sm text-muted md:min-h-0">
        {register.heading}
      </summary>
      <div className="overflow-x-auto">
        <table className="w-full text-sm">
          <thead>
            <tr className="text-left text-xs text-muted">
              <th className="px-[var(--s-3)] py-[var(--s-2)] font-medium">Лист</th>
              <th className="px-[var(--s-3)] py-[var(--s-2)] font-medium">Наименование</th>
              <th className="px-[var(--s-3)] py-[var(--s-2)] font-medium">Стр.</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-border">
            {register.entries.map((entry) => (
              <tr key={entry.number}>
                <td className="tabular px-[var(--s-3)] py-[var(--s-2)] align-top">
                  {entry.number}
                </td>
                <td className="px-[var(--s-3)] py-[var(--s-2)] align-top [overflow-wrap:anywhere]">
                  {entry.title}
                </td>
                <td className="tabular px-[var(--s-3)] py-[var(--s-2)] align-top text-muted">
                  {entry.page_index + 1}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  </li>
);

const Summary: FC<{ readonly data: SheetRegistersOut }> = ({ data }) => {
  const summary = data.last_extract;
  if (summary?.status !== 'succeeded') return null;
  return (
    <p className="tabular text-sm text-muted" data-testid="register-summary">
      Найдено ведомостей: {num(summary.registers)} · просмотрено ревизий:{' '}
      {num(summary.revisions_scanned)} из {num(summary.revisions_total)}
      {(summary.revisions_no_text ?? 0) > 0 &&
        ` · без текста страниц: ${summary.revisions_no_text} (сначала «Разобрать листы»)`}
      {(summary.revisions_unreadable ?? 0) > 0 && ` · не читается: ${summary.revisions_unreadable}`}
    </p>
  );
};

export const FrameRegistersPanel: FC<IPanelProps> = ({ projectId }) => {
  const registers = useSheetRegisters(projectId, true);
  const start = useStartRegisterExtract(projectId);
  const bulk = useBulkRegisterStatus(projectId);
  const client = useQueryClient();
  const data = registers.data;
  const active = isExtractActive(data);

  // Конец разбора меняет число кандидатов в проверках каркаса: перечитываем каркас.
  const wasActive = useRef(false);
  useEffect(() => {
    if (wasActive.current && !active) {
      void client.invalidateQueries({ queryKey: frameKeys.project(projectId) });
    }
    wasActive.current = active;
  }, [active, client, projectId]);

  const candidates = (data?.registers ?? [])
    .filter((item) => item.status === 'candidate')
    .map((item) => item.id);
  const error = start.error ?? bulk.error ?? registers.error;

  return (
    <section
      aria-labelledby="sheet-registers"
      className="flex flex-col gap-[var(--s-3)] rounded-[var(--radius-md)] border border-border bg-surface px-[var(--s-5)] py-[var(--s-4)]"
    >
      <div className="flex flex-wrap items-center gap-[var(--s-4)]">
        <h2 id="sheet-registers" className="text-base font-semibold">
          Ведомости листов
        </h2>
        <p className="min-w-0 flex-1 basis-[14rem] text-xs text-muted">
          Ведомость разбирается по тексту страниц PDF и сравнивается с паспортами листов того же
          документа. В проверки идёт подтверждённая ведомость.
        </p>
        <Button
          variant="primary"
          loading={start.isPending}
          disabled={active}
          onClick={() => start.mutate()}
        >
          Разобрать ведомости
        </Button>
      </div>
      {active && (
        <ProgressRow value={data?.last_extract?.progress ?? null} label="Разбор ведомостей" />
      )}
      {data?.last_extract?.status === 'failed' && (
        <p role="alert" className="text-sm text-danger">
          {errorMessage(data.last_extract.error_code ?? '')}
        </p>
      )}
      {data && <Summary data={data} />}
      {data && data.registers.length === 0 && data.last_extract?.status === 'succeeded' && (
        <p className="text-sm text-muted">Ведомостей листов в тексте страниц не найдено.</p>
      )}
      {data && data.registers.length > 0 && (
        <>
          {candidates.length > 0 && (
            <div>
              <Button
                compact
                disabled={bulk.isPending}
                onClick={() => bulk.mutate({ ids: candidates, status: 'confirmed' })}
              >
                Подтвердить все кандидаты ({candidates.length})
              </Button>
            </div>
          )}
          <ul className="divide-y divide-border">
            {data.registers.map((register) => (
              <RegisterItem
                key={register.id}
                register={register}
                busy={bulk.isPending}
                onStatus={(id, status) => bulk.mutate({ ids: [id], status })}
              />
            ))}
          </ul>
        </>
      )}
      {error !== null && (
        <p role="alert" className="text-sm text-danger">
          {extractMessage(error) ?? errorMessage(extractCode(error))}
        </p>
      )}
    </section>
  );
};
