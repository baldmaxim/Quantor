'use client';

import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import { classifyFiles, FileDropzone, type PickedFile } from '@/components/projects/FileDropzone';
import { useUploadQueue } from '@/components/projects/UploadQueue';
import { getUploadDialogState } from '@/components/projects/uploadDialogState';
import { UploadQueueList } from '@/components/projects/UploadQueueList';
import { Button, Dialog, DialogActions } from '@/components/ui';

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

  const [files, setFiles] = useState<readonly PickedFile[]>([]);
  const queue = useUploadQueue();

  const accepted = files.filter((item) => item.accepted);
  const busy = queue.running;
  const { primary, canUpload } = getUploadDialogState({
    pendingCount: accepted.length,
    running: busy,
    items: queue.items,
  });

  const submit = async () => {
    await queue.start({
      projectId,
      files: accepted.map((item) => item.file),
      keepDone: true,
      // Загруженный файл уходит из очереди выбранных; упавшие остаются для повтора.
      onFileDone: (done) => setFiles((current) => current.filter((item) => item.file !== done)),
    });
    // Обновляем и карточку, и список: там и там виден ход импорта.
    await queryClient.invalidateQueries({ queryKey: ['project', projectId] });
    await queryClient.invalidateQueries({ queryKey: ['projects'] });
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      busy={busy}
      title="Загрузить файлы"
      onExited={() => {
        setFiles([]);
        queue.reset();
      }}
      footer={
        <>
          {busy && (
            <Button variant="danger" onClick={queue.cancel}>
              Отменить
            </Button>
          )}
          <DialogActions>
            {primary === 'done' ? (
              <Button variant="primary" onClick={onClose}>
                Готово
              </Button>
            ) : (
              <>
                <Button onClick={onClose} disabled={busy}>
                  Отмена
                </Button>
                <Button
                  variant="primary"
                  onClick={() => void submit()}
                  disabled={!canUpload}
                  loading={busy}
                  loadingLabel="Загружаем…"
                >
                  Загрузить
                </Button>
              </>
            )}
          </DialogActions>
        </>
      }
    >
      <FileDropzone
        files={files}
        disabled={busy}
        onAdd={(added) => setFiles((current) => [...current, ...classifyFiles(added)])}
        onRemove={(index) => setFiles((current) => current.filter((_, i) => i !== index))}
      />

      <UploadQueueList items={queue.items} />
    </Dialog>
  );
};
