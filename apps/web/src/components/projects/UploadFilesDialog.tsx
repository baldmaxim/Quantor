'use client';

import { useQueryClient } from '@tanstack/react-query';
import { useEffect, useId, useState } from 'react';

import { classifyFiles, FileDropzone, type PickedFile } from '@/components/projects/FileDropzone';
import { useUploadQueue } from '@/components/projects/UploadQueue';
import { Button, ProgressRow, StatusBadge } from '@/components/ui';
import { formatBytes } from '@/lib/format';

/**
 * Загрузка файлов в существующий проект.
 *
 * Отличается от создания проекта только отсутствием поля имени, поэтому отдельный
 * компонент, а не флаг в первом: диалог с половиной выключенных полей читается хуже,
 * чем два простых.
 */

interface IUploadFilesDialogProps {
  projectId: string;
  open: boolean;
  onClose: () => void;
}

export const UploadFilesDialog = ({ projectId, open, onClose }: IUploadFilesDialogProps) => {
  const queryClient = useQueryClient();
  const titleId = useId();

  const [files, setFiles] = useState<readonly PickedFile[]>([]);
  const queue = useUploadQueue();

  const accepted = files.filter((item) => item.accepted);
  const busy = queue.running;

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
    await queue.start({ projectId, files: accepted.map((item) => item.file) });
    // Обновляем и карточку, и список: там и там виден ход импорта.
    await queryClient.invalidateQueries({ queryKey: ['project', projectId] });
    await queryClient.invalidateQueries({ queryKey: ['projects'] });
  };

  const finished = queue.items.length > 0 && !queue.running;

  return (
    <div
      // На телефоне окно прижато к низу и во всю ширину: до кнопок внизу дотягивается
      // большой палец, а центрированная карточка с полями по краям там только сужает
      // поля ввода.
      className="animate-scrim fixed inset-0 z-50 grid items-end justify-items-center bg-[var(--scrim)] sm:place-items-center sm:p-[var(--s-6)]"
      onMouseDown={(event) => {
        if (event.target === event.currentTarget && !busy) onClose();
      }}
    >
      <div
        role="dialog"
        aria-modal="true"
        aria-labelledby={titleId}
        className="animate-dialog safe-bottom flex max-h-[88dvh] w-full max-w-[620px] flex-col gap-[var(--s-6)] overflow-auto rounded-t-[var(--radius-lg)] border border-border-strong bg-surface-raised p-[var(--s-6)] shadow-[var(--shadow-2)] sm:rounded-b-[var(--radius-lg)] sm:p-[var(--s-7)]"
      >
        <h2 id={titleId} className="text-lg font-semibold">
          Загрузить файлы
        </h2>

        <FileDropzone
          files={files}
          disabled={busy}
          onAdd={(added) => setFiles((current) => [...current, ...classifyFiles(added)])}
          onRemove={(index) => setFiles((current) => current.filter((_, i) => i !== index))}
        />

        {queue.items.length > 0 && (
          <ul className="flex flex-col gap-[var(--s-4)]">
            {queue.items.map((item) => (
              <li key={item.id} className="flex flex-col gap-[var(--s-2)]">
                <div className="flex items-baseline gap-[var(--s-4)] text-xs">
                  <span className="min-w-0 flex-1 truncate">{item.name}</span>
                  <span className="mono text-muted">{formatBytes(item.size)}</span>
                  <StatusBadge
                    dot={false}
                    tone={
                      item.stage === 'ошибка'
                        ? 'danger'
                        : item.stage === 'готово'
                          ? 'success'
                          : 'accent'
                    }
                  >
                    {item.stage === 'готово' && item.duplicate ? 'уже был' : item.stage}
                  </StatusBadge>
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

        <div className="flex items-center gap-[var(--s-4)]">
          {busy && (
            <Button variant="danger" onClick={queue.cancel}>
              Отменить
            </Button>
          )}
          <div className="ml-auto flex gap-[var(--s-4)]">
            <Button onClick={onClose} disabled={busy}>
              {finished ? 'Закрыть' : 'Отмена'}
            </Button>
            <Button
              variant="primary"
              onClick={() => void submit()}
              disabled={busy || accepted.length === 0}
            >
              {busy ? 'Загружаем…' : 'Загрузить'}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
};
