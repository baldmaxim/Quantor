import type { FC } from 'react';

import { Button, Dialog, DialogActions } from '@/components/ui';

/** Подтверждение массовой отмены: выполняющиеся задания будут прерваны. */

export interface ICancelConfirmDialogProps {
  readonly open: boolean;
  readonly title: string;
  readonly description: string;
  /** Среди отменяемых есть выполняющиеся: показывается предупреждение. */
  readonly hasRunning: boolean;
  readonly busy: boolean;
  readonly onConfirm: () => void;
  readonly onClose: () => void;
}

export const CancelConfirmDialog: FC<ICancelConfirmDialogProps> = ({
  open,
  title,
  description,
  hasRunning,
  busy,
  onConfirm,
  onClose,
}) => (
  <Dialog
    open={open}
    onClose={onClose}
    busy={busy}
    title={title}
    description={description}
    footer={
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          Не отменять
        </Button>
        <Button variant="danger" onClick={onConfirm} disabled={busy}>
          Отменить задания
        </Button>
      </DialogActions>
    }
  >
    {hasRunning && (
      <p className="m-0 text-sm text-warning">
        Выполняющиеся задания будут прерваны: исполнитель остановит их при ближайшем продлении
        аренды.
      </p>
    )}
  </Dialog>
);
