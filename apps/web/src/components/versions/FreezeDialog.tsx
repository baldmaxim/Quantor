'use client';

import type { TenderVersionRead } from '@quantor/api-client';
import { useState } from 'react';

import { Button, Dialog, DialogActions } from '@/components/ui';
import { errorMessage, extractCode } from '@/lib/errors';
import { DOCUMENTS_FORMS, plural } from '@/lib/format';
import { hashStart, useFreezeTenderVersion } from '@/lib/tender-versions';

/**
 * Подтверждение заморозки.
 *
 * Заморозка необратима: после неё состав и подпись не меняет никто, даже администратор, —
 * это держит триггер базы. Поэтому окно называет, что именно будет зафиксировано, а после
 * заморозки показывает начало отпечатка комплекта: по нему версию потом узнают.
 */

interface IFreezeDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  version: TenderVersionRead;
}

export const FreezeDialog = ({ open, onClose, projectId, version }: IFreezeDialogProps) => {
  const freeze = useFreezeTenderVersion(projectId, version.id);
  const [hash, setHash] = useState<string | null>(null);

  const total = version.documents.length;
  const inModel = version.documents.filter((row) => row.use_in_model).length;

  return (
    <Dialog
      open={open}
      onClose={onClose}
      busy={freeze.isPending}
      title={hash ? 'Версия заморожена' : `Заморозить версию ${version.number}?`}
      onExited={() => {
        setHash(null);
        freeze.reset();
      }}
      footer={
        <DialogActions>
          {hash ? (
            <Button variant="primary" onClick={onClose}>
              Готово
            </Button>
          ) : (
            <>
              <Button onClick={onClose} disabled={freeze.isPending}>
                Отмена
              </Button>
              <Button
                variant="primary"
                loading={freeze.isPending}
                loadingLabel="Замораживаем…"
                disabled={total === 0}
                onClick={() =>
                  freeze.mutate(undefined, {
                    onSuccess: (frozen) => setHash(frozen.manifest_sha256),
                  })
                }
              >
                Заморозить
              </Button>
            </>
          )}
        </DialogActions>
      }
    >
      {hash ? (
        <div className="flex flex-col gap-[var(--s-4)]">
          <p className="text-sm">Отпечаток комплекта:</p>
          <p className="mono text-base break-all" title={hash}>
            {hashStart(hash)}
          </p>
          <p className="text-sm text-muted">
            Полный отпечаток — в карточке версии. Состав больше не меняется.
          </p>
        </div>
      ) : (
        <div className="flex flex-col gap-[var(--s-4)]">
          <p className="text-sm">
            В комплекте {total} {plural(total, DOCUMENTS_FORMS)}, в модель идёт {inModel}.
            {version.external_tender_id
              ? ` Связь с HUBTender: версия ${version.external_version ?? '—'}.`
              : ' Связи с HUBTender нет.'}
          </p>
          <p className="text-sm text-muted">
            После заморозки состав, разделы и подпись не меняются: исправить комплект можно только
            новой версией. Удалить ревизию, входящую в версию, тоже будет нельзя.
          </p>
          {freeze.error && (
            <p role="alert" className="text-sm text-danger">
              {errorMessage(extractCode(freeze.error))}
            </p>
          )}
        </div>
      )}
    </Dialog>
  );
};
