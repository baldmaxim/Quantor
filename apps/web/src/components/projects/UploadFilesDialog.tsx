'use client';

import { useQueryClient } from '@tanstack/react-query';
import { useMemo } from 'react';

import { FileDropzone } from '@/components/projects/FileDropzone';
import { FolderReport } from '@/components/projects/FolderReport';
import { useUploadQueue } from '@/components/projects/UploadQueue';
import { getUploadDialogState } from '@/components/projects/uploadDialogState';
import { UploadQueueList } from '@/components/projects/UploadQueueList';
import { usePickedFiles, type IExistingStems } from '@/components/projects/usePickedFiles';
import { Button, Dialog, DialogActions } from '@/components/ui';
import { baseName, isRecognizedPackage } from '@/lib/documentSections';
import { useProjectDocuments } from '@/lib/queries';
import { stemKey } from '@/lib/uploads/packageFolder';

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

  // Уже загруженные пакеты проекта: их комплекты в окне не предупреждение, а справка.
  const documents = useProjectDocuments(projectId, open);
  // PDF проекта: к ним прикрепится распознавание, выбранное отдельно от PDF.
  const existing = useMemo<IExistingStems>(() => {
    const items = documents.data?.items ?? [];
    const stems = (pick: (item: (typeof items)[number]) => boolean): ReadonlySet<string> =>
      new Set(items.filter(pick).map((item) => stemKey(baseName(item.display_name))));
    return {
      packages: stems((item) => isRecognizedPackage(item.display_name, item.document_kind)),
      pdfs: stems(
        (item) =>
          item.document_kind === 'pdf' &&
          !isRecognizedPackage(item.display_name, item.document_kind),
      ),
    };
  }, [documents.data]);

  const picked = usePickedFiles(existing);
  const { files, folderReport } = picked;
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
      onFileDone: picked.removeDone,
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
        picked.reset();
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
        onAdd={picked.addFiles}
        onRemove={picked.removeAt}
        onAddFolder={picked.addFolder}
      />

      <FolderReport report={folderReport} />

      <UploadQueueList items={queue.items} />
    </Dialog>
  );
};
