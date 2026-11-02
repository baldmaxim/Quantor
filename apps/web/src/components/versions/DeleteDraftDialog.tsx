'use client';

import type { TenderVersionRead } from '@quantor/api-client';

import { Button, Dialog, DialogActions } from '@/components/ui';
import { errorMessage, extractCode } from '@/lib/errors';
import { useDeleteTenderVersion } from '@/lib/tender-versions';

/**
 * Подтверждение удаления черновика.
 *
 * Удаление необратимо: подпись, связь с HUBTender и правки состава восстановить нельзя.
 * Документы и ревизии проекта остаются на месте.
 */

interface IDeleteDraftDialogProps {
  open: boolean;
  onClose: () => void;
  onDeleted: () => void;
  projectId: string;
  version: TenderVersionRead;
}

export const DeleteDraftDialog = ({
  open,
  onClose,
  onDeleted,
  projectId,
  version,
}: IDeleteDraftDialogProps) => {
  const remove = useDeleteTenderVersion(projectId, version.id);

  return (
    <Dialog
      open={open}
      onClose={onClose}
      busy={remove.isPending}
      title={`Удалить черновик версии ${version.number}?`}
      onExited={() => remove.reset()}
      footer={
        <DialogActions>
          <Button onClick={onClose} disabled={remove.isPending}>
            Отмена
          </Button>
          <Button
            variant="danger"
            loading={remove.isPending}
            loadingLabel="Удаляем…"
            onClick={() => remove.mutate(undefined, { onSuccess: onDeleted })}
          >
            Удалить
          </Button>
        </DialogActions>
      }
    >
      <div className="flex flex-col gap-[var(--s-4)]">
        <p className="text-sm">
          Подпись, связь с HUBTender и правки состава восстановить будет нельзя. Документы и ревизии
          проекта останутся.
        </p>
        {remove.error && (
          <p role="alert" className="text-sm text-danger">
            {errorMessage(extractCode(remove.error))}
          </p>
        )}
      </div>
    </Dialog>
  );
};
