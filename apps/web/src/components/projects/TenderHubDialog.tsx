'use client';

import { importTender, type TenderBriefRead } from '@quantor/api-client';
import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useEffect, useId, useState } from 'react';

import {
  Button,
  EmptyState,
  ErrorState,
  SearchInput,
  Skeleton,
  StatusBadge,
  cx,
} from '@/components/ui';
import { useListAnimation } from '@/lib/animate';
import { errorMessage } from '@/lib/errors';
import { useTenders } from '@/lib/queries';

/**
 * Выбор тендера в TenderHUB.
 *
 * Портал берёт из тендера только то, что делает его проектом: номер, название и
 * заказчика. Позиции и строки смет сюда не приходят — считать объёмы портал на этом
 * этапе не умеет, и показывать чужой расчёт как свой было бы неправдой.
 *
 * Ключ доступа живёт на сервере: браузер ходит в портал, портал — в TenderHUB.
 */

interface ITenderHubDialogProps {
  open: boolean;
  onClose: () => void;
}

export const TenderHubDialog = ({ open, onClose }: ITenderHubDialogProps) => {
  const router = useRouter();
  const queryClient = useQueryClient();
  const titleId = useId();

  const [search, setSearch] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [failure, setFailure] = useState<{ code: string; text: string } | null>(null);

  const tenders = useTenders(search, open);
  const list = useListAnimation<HTMLUListElement>(open);

  useEffect(() => {
    if (!open) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busyId) onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, busyId, onClose]);

  if (!open) return null;

  const connect = async (tender: TenderBriefRead) => {
    setFailure(null);
    setBusyId(tender.id);

    try {
      const response = await importTender({
        throwOnError: true,
        body: { tender_id: tender.id },
      });
      const projectId = response.data?.id;
      if (!projectId) throw new Error('Сервер не вернул идентификатор проекта');

      await queryClient.invalidateQueries({ queryKey: ['projects'] });
      await queryClient.invalidateQueries({ queryKey: ['tenderhub'] });
      router.push(`/projects/${projectId}`);
    } catch (error) {
      const code = extractCode(error);
      setFailure({ code, text: errorMessage(code) });
    } finally {
      setBusyId(null);
    }
  };

  const items = tenders.data ?? [];

  return (
    <div
      className="animate-scrim fixed inset-0 z-50 grid items-end justify-items-center bg-[var(--scrim)] sm:place-items-center sm:p-[var(--s-6)]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busyId) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="animate-dialog safe-bottom flex max-h-[88dvh] w-full max-w-[720px] flex-col gap-[var(--s-5)] overflow-hidden rounded-t-[var(--radius-lg)] border border-border-strong bg-surface-raised p-[var(--s-6)] shadow-[var(--shadow-2)] sm:rounded-b-[var(--radius-lg)] sm:p-[var(--s-7)]"
      >
        <div className="flex flex-none flex-col gap-[var(--s-2)]">
          <h2 id={titleId} className="text-lg font-semibold">
            Проект из TenderHUB
          </h2>
          <p className="text-sm text-muted">
            Портал возьмёт номер, название и заказчика. Позиции и сметные строки не переносятся —
            документацию нужно будет загрузить отдельно.
          </p>
        </div>

        <SearchInput
          label="Поиск по номеру, названию или заказчику"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          onClear={() => setSearch('')}
          className="w-full flex-none"
        />

        {failure && (
          <ErrorState title="Проект не создан" code={failure.code} description={failure.text} />
        )}

        <div className="scroll-area -mx-[var(--s-3)] min-h-0 flex-1 px-[var(--s-3)]">
          {tenders.isPending && (
            <div className="flex flex-col gap-[var(--s-4)]">
              {[0, 1, 2, 3].map((row) => (
                <Skeleton key={row} className="h-[52px] w-full" />
              ))}
            </div>
          )}

          {tenders.isError && (
            <ErrorState
              title="TenderHUB не ответил"
              description={errorMessage(extractCode(tenders.error))}
              onRetry={() => void tenders.refetch()}
            />
          )}

          {tenders.data?.length === 0 && (
            <EmptyState
              compact
              title={search ? 'Ничего не найдено' : 'Тендеров нет'}
              description={
                search
                  ? 'Поиск идёт по номеру, названию и заказчику.'
                  : 'Ключу доступа не видно ни одного активного тендера.'
              }
            />
          )}

          <ul ref={list} className="flex list-none flex-col">
            {items.map((tender) => (
              <TenderRow
                key={tender.id}
                tender={tender}
                busy={busyId === tender.id}
                disabled={busyId !== null}
                onConnect={() => void connect(tender)}
                onOpen={(projectId) => router.push(`/projects/${projectId}`)}
              />
            ))}
          </ul>
        </div>

        <div className="flex flex-none justify-end">
          <Button onClick={onClose} disabled={busyId !== null}>
            Закрыть
          </Button>
        </div>
      </div>
    </div>
  );
};

interface ITenderRowProps {
  tender: TenderBriefRead;
  busy: boolean;
  disabled: boolean;
  onConnect: () => void;
  onOpen: (projectId: string) => void;
}

const TenderRow = ({ tender, busy, disabled, onConnect, onOpen }: ITenderRowProps) => {
  const linked = tender.imported_project_id;

  return (
    <li className="flex flex-wrap items-center gap-x-[var(--s-5)] gap-y-[var(--s-3)] border-b border-border py-[var(--s-4)] last:border-b-0">
      <span className="flex min-w-0 basis-full flex-col gap-[var(--s-1)] sm:basis-auto sm:flex-1">
        <span className="flex flex-wrap items-center gap-[var(--s-4)]">
          {tender.tender_number && (
            <span className="mono text-xs text-muted">{tender.tender_number}</span>
          )}
          <span className="wrap-anywhere text-sm font-medium">
            {tender.title || 'Без названия'}
          </span>
        </span>
        <span className="flex flex-wrap items-center gap-x-[var(--s-4)] gap-y-[var(--s-1)] text-xs text-muted">
          {tender.client_name && <span className="wrap-anywhere">{tender.client_name}</span>}
          {tender.construction_scope && <span>{tender.construction_scope}</span>}
          {typeof tender.version === 'number' && <span>версия {tender.version}</span>}
        </span>
      </span>

      {/* Тендер, уже ставший проектом, ведёт в него: создавать второй по той же записи
          нельзя, и предлагать это кнопкой было бы обманом. */}
      {linked ? (
        <span className={cx('flex flex-none items-center gap-[var(--s-4)]')}>
          <StatusBadge tone="success">подключён</StatusBadge>
          <Button onClick={() => onOpen(linked)}>Открыть</Button>
        </span>
      ) : (
        <Button variant="primary" className="flex-none" disabled={disabled} onClick={onConnect}>
          {busy ? 'Создаём…' : 'Создать проект'}
        </Button>
      )}
    </li>
  );
};

const extractCode = (error: unknown): string => {
  const detail = (error as { detail?: { code?: string } } | null)?.detail;
  if (detail?.code) return detail.code;

  const nested = (error as { error?: { detail?: { code?: string } } } | null)?.error?.detail;
  if (nested?.code) return nested.code;

  return 'NETWORK_ERROR';
};
