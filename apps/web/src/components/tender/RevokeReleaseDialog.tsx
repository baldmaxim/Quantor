'use client';

import type { TenderBaseReleaseRead } from '@quantor/api-client';
import type { FC } from 'react';

import { Button, Dialog, DialogActions } from '@/components/ui';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

/** Подтверждение отзыва выпуска базы: расчёты на отозванную базу портал больше не принимает. */

interface IDialogProps {
  readonly release: TenderBaseReleaseRead | null;
  readonly busy: boolean;
  readonly error: unknown;
  readonly onClose: () => void;
  readonly onConfirm: (releaseId: string) => void;
}

export const RevokeReleaseDialog: FC<IDialogProps> = ({
  release,
  busy,
  error,
  onClose,
  onConfirm,
}) => (
  <Dialog
    open={release !== null}
    onClose={onClose}
    busy={busy}
    title="Отозвать выпуск базы?"
    description={
      release
        ? `Выпуск #${release.number} перестанет приниматься для новых расчётов. Уже загруженные версии не изменятся.`
        : undefined
    }
    footer={
      <DialogActions>
        <Button onClick={onClose} disabled={busy}>
          Не отзывать
        </Button>
        <Button
          variant="danger"
          disabled={busy || release === null}
          onClick={() => release && onConfirm(release.id)}
        >
          Отозвать
        </Button>
      </DialogActions>
    }
  >
    {error !== null && (
      <p role="alert" className="m-0 text-sm text-danger">
        {extractMessage(error) ?? errorMessage(extractCode(error))}
      </p>
    )}
  </Dialog>
);
