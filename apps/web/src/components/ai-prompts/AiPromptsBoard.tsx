'use client';

import type { AiPromptSummary } from '@quantor/api-client';
import { useState, type FC } from 'react';

import {
  Button,
  Dialog,
  DialogActions,
  EmptyState,
  ErrorState,
  SegmentedControl,
  SkeletonRows,
  StatusBadge,
} from '@/components/ui';
import { ClearableInput } from '@/components/ui/ClearableInput';
import { ClearableTextarea } from '@/components/ui/ClearableTextarea';
import {
  AI_PROMPT_ROLE_LABEL,
  useActivateAiPrompt,
  useAiPrompt,
  useAiPromptList,
  useCreateAiPrompt,
  type AiPromptRole,
} from '@/lib/ai-prompts/ai-prompt-queries';
import { QUEUE_ACCESS_PERMISSION } from '@/lib/jobs/permissions';
import { formatWhen } from '@/lib/format';
import { useSession } from '@/lib/session';

import { AiPromptStatsTable } from './AiPromptStatsTable';

/** Промты ИИ-проверки: версии роли, просмотр текста, новая версия, активация, статистика. */

const ROLES: readonly { value: AiPromptRole; label: string }[] = [
  { value: 'corrector', label: AI_PROMPT_ROLE_LABEL.corrector },
  { value: 'verifier', label: AI_PROMPT_ROLE_LABEL.verifier },
];

const STATUS: Readonly<
  Record<AiPromptSummary['status'], { label: string; tone: 'success' | 'neutral' | 'warning' }>
> = {
  active: { label: 'активна', tone: 'success' },
  draft: { label: 'черновик', tone: 'warning' },
  archived: { label: 'архив', tone: 'neutral' },
};

const author = (row: AiPromptSummary): string =>
  row.created_by === null ? 'система' : row.created_by.slice(0, 8);

interface IRoleSectionProps {
  readonly role: AiPromptRole;
}

const RoleSection: FC<IRoleSectionProps> = ({ role }) => {
  const list = useAiPromptList(role);
  const create = useCreateAiPrompt();
  const activate = useActivateAiPrompt();

  const [viewedId, setViewedId] = useState<string | null>(null);
  const [drafting, setDrafting] = useState(false);
  const [text, setText] = useState('');
  const [note, setNote] = useState('');
  const [pending, setPending] = useState<AiPromptSummary | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const rows = list.data ?? [];
  const active = rows.find((row) => row.status === 'active') ?? null;
  const shownId = viewedId ?? active?.id ?? null;
  const shown = useAiPrompt(shownId);
  const base = useAiPrompt(active?.id ?? null);

  const startDraft = () => {
    setText(base.data?.text ?? '');
    setNote('');
    setMessage(null);
    setDrafting(true);
  };

  const submit = () =>
    create.mutate(
      { role, text, note: note.trim() === '' ? null : note.trim() },
      {
        onSuccess: (created) => {
          setDrafting(false);
          setViewedId(created.id);
          setMessage(`Создана версия ${created.version} (черновик)`);
        },
        onError: () => setMessage('Не удалось создать версию'),
      },
    );

  const confirmActivation = () => {
    if (pending === null) return;
    activate.mutate(pending.id, {
      onSuccess: (done) => {
        setPending(null);
        setViewedId(null);
        setMessage(`Версия ${done.version} теперь активна`);
      },
      onError: () => {
        setPending(null);
        setMessage('Не удалось активировать версию');
      },
    });
  };

  if (list.isPending) return <SkeletonRows rows={4} />;
  if (list.isError) {
    return <ErrorState title="Не удалось получить версии" onRetry={() => void list.refetch()} />;
  }

  return (
    <div className="flex flex-col gap-[var(--s-6)]">
      <section className="flex flex-col gap-[var(--s-4)] rounded-[var(--radius-md)] border border-border-strong bg-surface p-[var(--s-5)]">
        <div className="flex flex-col gap-[var(--s-3)] md:flex-row md:items-center">
          <h2 className="m-0 text-sm font-medium">
            {active === null ? 'Активной версии нет' : `Активная версия: v${active.version}`}
          </h2>
          <Button className="md:ml-auto" onClick={startDraft} disabled={base.data === undefined}>
            Новая версия
          </Button>
        </div>
        {message !== null && (
          <p role="status" className="m-0 text-sm text-text">
            {message}
          </p>
        )}
        {shown.data && (
          <>
            <p className="m-0 text-xs text-muted">
              Текст версии {shown.data.version} ({STATUS[shown.data.status].label}),{' '}
              {shown.data.text_bytes} байт
            </p>
            <pre
              aria-label="Текст промта"
              className="m-0 max-h-[360px] overflow-auto overscroll-contain rounded-[var(--radius-sm)] border border-border bg-surface-muted p-[var(--s-4)] text-sm whitespace-pre-wrap [overflow-wrap:anywhere]"
            >
              {shown.data.text}
            </pre>
          </>
        )}
      </section>

      {rows.length === 0 && <EmptyState compact title="Версий нет" />}
      {rows.length > 0 && (
        <ul
          aria-label="Версии промта"
          className="m-0 flex list-none flex-col overflow-hidden rounded-[var(--radius-md)] border border-border-strong bg-surface p-0"
        >
          {rows.map((row) => (
            <li
              key={row.id}
              className="flex flex-col gap-[var(--s-3)] border-b border-border px-[var(--s-5)] py-[var(--s-4)] last:border-b-0 md:flex-row md:items-center"
            >
              <div className="flex min-w-0 flex-1 flex-col gap-[var(--s-2)]">
                <div className="flex flex-wrap items-center gap-[var(--s-3)] text-sm">
                  <span className="font-medium">v{row.version}</span>
                  <StatusBadge tone={STATUS[row.status].tone}>
                    {STATUS[row.status].label}
                  </StatusBadge>
                  <span className="text-muted">
                    {author(row)} · {formatWhen(row.created_at)}
                  </span>
                </div>
                {row.note !== null && (
                  <p className="m-0 text-sm text-muted [overflow-wrap:anywhere]">{row.note}</p>
                )}
              </div>
              <div className="flex flex-col gap-[var(--s-3)] md:flex-row">
                <Button onClick={() => setViewedId(row.id)}>Просмотр v{row.version}</Button>
                {row.status !== 'active' && (
                  <Button variant="primary" onClick={() => setPending(row)}>
                    Сделать активной
                  </Button>
                )}
              </div>
            </li>
          ))}
        </ul>
      )}

      {drafting && (
        <section
          aria-label="Новая версия"
          className="flex flex-col gap-[var(--s-4)] rounded-[var(--radius-md)] border border-border-strong bg-surface p-[var(--s-5)]"
        >
          <h2 className="m-0 text-sm font-medium">Новая версия</h2>
          <ClearableTextarea
            label="Текст промта"
            value={text}
            onChange={(event) => setText(event.target.value)}
            onClear={() => setText('')}
            wrapperClassName="flex w-full"
            className="min-h-[280px] font-mono"
          />
          <ClearableInput
            label="Заметка"
            value={note}
            maxLength={500}
            onChange={(event) => setNote(event.target.value)}
            onClear={() => setNote('')}
            wrapperClassName="flex w-full"
            className="h-[44px] w-full rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:h-[var(--h-ctl)] md:text-sm"
          />
          <div className="flex flex-col gap-[var(--s-3)] md:flex-row">
            <Button
              variant="primary"
              onClick={submit}
              disabled={text.trim() === '' || create.isPending}
            >
              Создать черновик
            </Button>
            <Button onClick={() => setDrafting(false)} disabled={create.isPending}>
              Отмена
            </Button>
          </div>
        </section>
      )}

      <AiPromptStatsTable role={role} />

      <Dialog
        open={pending !== null}
        onClose={() => setPending(null)}
        busy={activate.isPending}
        title="Сделать версию активной"
        description={`Версия ${pending?.version ?? ''} станет активной для роли «${AI_PROMPT_ROLE_LABEL[role]}», прежняя уйдёт в архив. Следующие прогоны возьмут новый текст.`}
        footer={
          <DialogActions>
            <Button onClick={() => setPending(null)} disabled={activate.isPending}>
              Отмена
            </Button>
            <Button variant="primary" onClick={confirmActivation} disabled={activate.isPending}>
              Активировать
            </Button>
          </DialogActions>
        }
      >
        <span />
      </Dialog>
    </div>
  );
};

export const AiPromptsBoard: FC = () => {
  const session = useSession();
  const [role, setRole] = useState<AiPromptRole>('corrector');

  if (session.isPending) return <SkeletonRows rows={4} />;
  if (!(session.data?.permissions?.includes(QUEUE_ACCESS_PERMISSION) ?? false)) {
    return (
      <EmptyState title="Нет доступа" description="Промты ИИ доступны системным администраторам." />
    );
  }

  return (
    <div className="flex flex-col gap-[var(--s-5)]">
      <SegmentedControl label="Роль" value={role} options={ROLES} onChange={setRole} />
      <RoleSection key={role} role={role} />
    </div>
  );
};
