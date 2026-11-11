'use client';

import { useQueryClient } from '@tanstack/react-query';
import { useState } from 'react';

import {
  classifyFiles,
  FileDropzone,
  packagePicked,
  type PickedFile,
} from '@/components/projects/FileDropzone';
import { FolderReport, type FolderReportData } from '@/components/projects/FolderReport';
import { useUploadQueue } from '@/components/projects/UploadQueue';
import { getUploadDialogState } from '@/components/projects/uploadDialogState';
import { UploadQueueList } from '@/components/projects/UploadQueueList';
import { Button, Dialog, DialogActions } from '@/components/ui';
import { planFolderUpload, type IFolderEntry } from '@/lib/uploads/packageFolder';

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
  const [folderReport, setFolderReport] = useState<FolderReportData | null>(null);
  const queue = useUploadQueue();

  const accepted = files.filter((item) => item.accepted);
  const busy = queue.running;
  const { primary, canUpload } = getUploadDialogState({
    pendingCount: accepted.length,
    running: busy,
    items: queue.items,
  });

  const addFolder = (entries: IFolderEntry[]) => {
    const plan = planFolderUpload(entries);
    const added = [...plan.packages.map(packagePicked), ...classifyFiles(plan.plainFiles)];
    setFiles((current) => [...current, ...added]);
    setFolderReport({ warnings: plan.warnings, skipped: plan.skipped, added: added.length });
  };

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
        setFolderReport(null);
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
        onAddFolder={addFolder}
      />

      <FolderReport report={folderReport} />

      <UploadQueueList items={queue.items} />
    </Dialog>
  );
};
