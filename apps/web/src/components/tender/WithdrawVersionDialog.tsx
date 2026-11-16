'use client';

import type { TenderCalcVersionRead } from '@quantor/api-client';
import type { FC } from 'react';

import { Button, Dialog, DialogActions } from '@/components/ui';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';
import { useWithdrawTenderVersion } from '@/lib/tender/queries';

/** Подтверждение отзыва версии: отозванная версия остаётся в истории, но не действует. */

interface IDialogProps {
  readonly projectId: string;
  readonly version: TenderCalcVersionRead;
  readonly open: boolean;
  readonly onClose: () => void;
}

export const WithdrawVersionDialog: FC<IDialogProps> = ({ projectId, version, open, onClose }) => {
  const withdraw = useWithdrawTenderVersion(projectId);
  const busy = withdraw.isPending;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      busy={busy}
      title="Отозвать версию?"
      description={`Версия №${version.number} «${version.label}» перестанет действовать. Файлы и история сохранятся; если есть прежняя версия, она снова станет действующей.`}
      footer={
        <DialogActions>
          <Button onClick={onClose} disabled={busy}>
            Не отзывать
          </Button>
          <Button
            variant="danger"
            disabled={busy}
            onClick={() => withdraw.mutate(version.id, { onSuccess: onClose })}
          >
            Отозвать
          </Button>
        </DialogActions>
      }
    >
      {withdraw.isError && (
        <p role="alert" className="m-0 text-sm text-danger">
          {extractMessage(withdraw.error) ?? errorMessage(extractCode(withdraw.error))}
        </p>
      )}
    </Dialog>
  );
};
