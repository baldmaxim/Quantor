'use client';

import { importTender, type TenderBriefRead } from '@quantor/api-client';
import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useState } from 'react';

import {
  Button,
  Dialog,
  DialogActions,
  EmptyState,
  ErrorState,
  SearchInput,
  Skeleton,
  StatusBadge,
  cx,
} from '@/components/ui';
import { useListAnimation } from '@/lib/animate';
import { errorMessage, extractCode } from '@/lib/errors';
import { useFeatures, useTenders } from '@/lib/queries';
import { TENDER_VERSIONS_FEATURE } from '@/lib/tender-versions';

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

  const [search, setSearch] = useState('');
  const [busyId, setBusyId] = useState<string | null>(null);
  const [failure, setFailure] = useState<{ code: string; text: string } | null>(null);

  const tenders = useTenders(search, open);
  const list = useListAnimation<HTMLUListElement>(open);
  const features = useFeatures();

  // Другая версия уже занятого номера ведёт в существующий проект (ADR-0035). Экран версий
  // закрыт флагом: без него остаётся карточка проекта.
  const projectHref = (projectId: string): string =>
    features[TENDER_VERSIONS_FEATURE] === true
      ? `/projects/${projectId}/versions`
      : `/projects/${projectId}`;

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
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      busy={busyId !== null}
      title="Проект из TenderHUB"
      description="Портал возьмёт номер, название и заказчика. Позиции и сметные строки не переносятся — документацию нужно будет загрузить отдельно."
      onExited={() => {
        setSearch('');
        setFailure(null);
      }}
      // Поиск закреплён: список под ним длинный, и уехавшее вверх поле пришлось бы
      // искать прокруткой обратно.
      toolbar={
        <SearchInput
          label="Поиск по номеру, названию или заказчику"
          value={search}
          onChange={(event) => setSearch(event.target.value)}
          onClear={() => setSearch('')}
          className="w-full"
        />
      }
      footer={
        <DialogActions>
          <Button onClick={onClose} disabled={busyId !== null}>
            Закрыть
          </Button>
        </DialogActions>
      }
    >
      {failure && (
        <ErrorState title="Проект не создан" code={failure.code} description={failure.text} />
      )}

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
            onOpenVersions={(projectId) => router.push(projectHref(projectId))}
          />
        ))}
      </ul>
    </Dialog>
  );
};

interface ITenderRowProps {
  tender: TenderBriefRead;
  busy: boolean;
  disabled: boolean;
  onConnect: () => void;
  onOpen: (projectId: string) => void;
  onOpenVersions: (projectId: string) => void;
}

const TenderRow = ({
  tender,
  busy,
  disabled,
  onConnect,
  onOpen,
  onOpenVersions,
}: ITenderRowProps) => {
  const linked = tender.imported_project_id;
  const sameNumber = tender.same_number_project_id;

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
      ) : sameNumber ? (
        // Номер уже занят проектом: вместо «Создать проект» — переход к нему на экран версий.
        <span className="flex flex-none flex-wrap items-center gap-[var(--s-4)]">
          <StatusBadge tone="warning">номер уже в проекте</StatusBadge>
          <Button variant="primary" onClick={() => onOpenVersions(sameNumber)}>
            Версии проекта
          </Button>
        </span>
      ) : (
        <Button
          variant="primary"
          className="flex-none"
          disabled={disabled}
          loading={busy}
          loadingLabel="Создаём…"
          onClick={onConnect}
        >
          Создать проект
        </Button>
      )}
    </li>
  );
};
