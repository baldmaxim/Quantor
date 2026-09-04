'use client';

import { createProject } from '@quantor/api-client';
import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useEffect, useId, useState } from 'react';

import { classifyFiles, FileDropzone, type PickedFile } from '@/components/projects/FileDropzone';
import { useUploadQueue } from '@/components/projects/UploadQueue';
import { Button, ErrorState, ProgressRow, StatusBadge } from '@/components/ui';
import { errorMessage } from '@/lib/errors';
import { formatBytes } from '@/lib/format';

/**
 * Создание проекта и загрузка первых файлов.
 *
 * Один шаг вместо мастера: полей всего два — имя и файлы, — и разбивать это на страницы
 * значило бы делать вид, что работа сложнее, чем есть.
 *
 * Проект создаётся до отправки файлов: загрузка идёт в уже существующий проект, и при
 * отказе на середине пользователь не теряет введённое имя и не остаётся с висящими файлами.
 */

interface ICreateProjectDialogProps {
  open: boolean;
  onClose: () => void;
}

export const CreateProjectDialog = ({ open, onClose }: ICreateProjectDialogProps) => {
  const router = useRouter();
  const queryClient = useQueryClient();
  const nameId = useId();

  const [name, setName] = useState('');
  const [files, setFiles] = useState<readonly PickedFile[]>([]);
  const [creating, setCreating] = useState(false);
  const [failure, setFailure] = useState<{ code: string; text: string } | null>(null);

  const queue = useUploadQueue();

  const accepted = files.filter((item) => item.accepted);
  const rejected = files.length - accepted.length;
  const busy = creating || queue.running;
  const canSubmit = name.trim().length > 0 && !busy;

  useEffect(() => {
    if (!open) return;

    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape' && !busy) onClose();
    };
    document.addEventListener('keydown', onKeyDown);
    return () => document.removeEventListener('keydown', onKeyDown);
  }, [open, busy, onClose]);

  if (!open) return null;

  const submit = async () => {
    setFailure(null);
    setCreating(true);

    try {
      const response = await createProject({ throwOnError: true, body: { name: name.trim() } });
      const projectId = response.data?.id;
      if (!projectId) throw new Error('Сервер не вернул идентификатор проекта');

      setCreating(false);
      await queryClient.invalidateQueries({ queryKey: ['projects'] });

      if (accepted.length > 0) {
        await queue.start({ projectId, files: accepted.map((item) => item.file) });
        await queryClient.invalidateQueries({ queryKey: ['projects'] });
      }

      router.push(`/projects/${projectId}`);
    } catch (error) {
      setCreating(false);
      const code = extractCode(error);
      setFailure({ code, text: errorMessage(code) });
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 grid place-items-center bg-[var(--scrim)] p-[var(--s-6)]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${nameId}-title`}
        className="flex max-h-[86dvh] w-full max-w-[620px] flex-col gap-[var(--s-6)] overflow-auto rounded-[var(--radius-lg)] border border-border-strong bg-surface-raised p-[var(--s-7)] shadow-[var(--shadow-2)]"
      >
        <h2 id={`${nameId}-title`} className="text-lg font-semibold">
          Новый проект
        </h2>

        <label className="flex flex-col gap-[var(--s-3)]">
          <span className="text-sm">Название проекта</span>
          <input
            autoFocus
            value={name}
            disabled={busy}
            onChange={(event) => setName(event.target.value)}
            placeholder="Например: ЖК «Северный», корпус 3 — АР"
            className="h-[var(--h-ctl)] rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-5)] text-sm text-text placeholder:text-muted disabled:opacity-60"
          />
        </label>

        <FileDropzone
          files={files}
          disabled={busy}
          onAdd={(added) => setFiles((current) => [...current, ...classifyFiles(added)])}
          onRemove={(index) => setFiles((current) => current.filter((_, i) => i !== index))}
        />

        {rejected > 0 && (
          <p className="text-xs text-danger">
            {rejected === 1
              ? 'Один файл не будет загружен'
              : `${rejected} файла не будут загружены`}
            : портал принимает только перечисленные типы.
          </p>
        )}

        {queue.items.length > 0 && (
          <ul className="flex flex-col gap-[var(--s-4)]">
            {queue.items.map((item) => (
              <li key={item.id} className="flex flex-col gap-[var(--s-2)]">
                <div className="flex items-baseline gap-[var(--s-4)] text-xs">
                  <span className="min-w-0 flex-1 truncate">{item.name}</span>
                  <span className="mono text-muted">{formatBytes(item.size)}</span>
                  <UploadBadge stage={item.stage} duplicate={item.duplicate} />
                </div>

                {item.stage === 'загрузка' && (
                  <ProgressRow value={item.fraction} label={`Загрузка ${item.name}`} />
                )}

                {item.errorText && (
                  <p className="text-xs text-danger">
                    {item.errorText}
                    {item.errorCode && <span className="mono text-muted"> · {item.errorCode}</span>}
                  </p>
                )}
              </li>
            ))}
          </ul>
        )}

        {failure && (
          <ErrorState title="Проект не создан" code={failure.code} description={failure.text} />
        )}

        <div className="flex items-center gap-[var(--s-4)]">
          {queue.running && (
            <Button variant="danger" onClick={queue.cancel}>
              Отменить загрузку
            </Button>
          )}
          <div className="ml-auto flex gap-[var(--s-4)]">
            <Button onClick={onClose} disabled={busy}>
              Отмена
            </Button>
            <Button variant="primary" onClick={() => void submit()} disabled={!canSubmit}>
              {busy ? 'Создаём…' : 'Создать проект'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};

const STAGE_TONE = {
  ожидание: 'neutral',
  загрузка: 'accent',
  готово: 'success',
  ошибка: 'danger',
  отменено: 'neutral',
} as const;

const UploadBadge = ({
  stage,
  duplicate,
}: {
  stage: keyof typeof STAGE_TONE;
  duplicate: boolean;
}) => (
  <StatusBadge tone={STAGE_TONE[stage]} dot={false}>
    {/* Повтор — не ошибка: файл уже был загружен, и вторая копия не создаётся. */}
    {stage === 'готово' && duplicate ? 'уже был' : stage}
  </StatusBadge>
);

const extractCode = (error: unknown): string => {
  const detail = (error as { detail?: { code?: string } } | null)?.detail;
  if (detail?.code) return detail.code;

  const nested = (error as { error?: { detail?: { code?: string } } } | null)?.error?.detail;
  if (nested?.code) return nested.code;

  return 'NETWORK_ERROR';
};
