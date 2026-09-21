'use client';

import { createProject } from '@quantor/api-client';
import { useQueryClient } from '@tanstack/react-query';
import { useRouter } from 'next/navigation';
import { useId, useState } from 'react';

import { classifyFiles, FileDropzone, type PickedFile } from '@/components/projects/FileDropzone';
import { useUploadQueue } from '@/components/projects/UploadQueue';
import { UploadQueueList } from '@/components/projects/UploadQueueList';
import { Button, Dialog, DialogActions, ErrorState } from '@/components/ui';
import { errorMessage, extractCode } from '@/lib/errors';

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
    <Dialog
      open={open}
      onClose={onClose}
      busy={busy}
      title="Новый проект"
      // Окно живёт в разметке постоянно, поэтому введённое имя и прошлую очередь
      // нужно обнулить явно: иначе они встретят пользователя при следующем открытии.
      onExited={() => {
        setName('');
        setFiles([]);
        setFailure(null);
        queue.reset();
      }}
      footer={
        <>
          {queue.running && (
            <Button variant="danger" onClick={queue.cancel}>
              Отменить загрузку
            </Button>
          )}
          <DialogActions>
            <Button onClick={onClose} disabled={busy}>
              Отмена
            </Button>
            <Button
              variant="primary"
              onClick={() => void submit()}
              disabled={!canSubmit}
              loading={busy}
              loadingLabel="Создаём…"
            >
              Создать проект
            </Button>
          </DialogActions>
        </>
      }
    >
      <label className="flex flex-col gap-[var(--s-3)]">
        <span className="text-sm">Название проекта</span>
        <input
          autoFocus
          id={nameId}
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
          {rejected === 1 ? 'Один файл не будет загружен' : `${rejected} файла не будут загружены`}:
          портал принимает только перечисленные типы.
        </p>
      )}

      <UploadQueueList items={queue.items} />

      {failure && (
        <ErrorState title="Проект не создан" code={failure.code} description={failure.text} />
      )}
    </Dialog>
  );
};
