'use client';

import { useState, type FormEvent } from 'react';

import { Button, Dialog, DialogActions } from '@/components/ui';
import { ClearableInput } from '@/components/ui/ClearableInput';
import { errorMessage, extractCode } from '@/lib/errors';
import { useCreateTenderVersion } from '@/lib/tender-versions';

/**
 * Новый черновик версии. Состав сервер заполняет последними ревизиями документов проекта —
 * дальше его правят в карточке версии. Связь с HUBTender ставится там же, когда версия есть.
 */

interface ICreateDraftDialogProps {
  open: boolean;
  onClose: () => void;
  projectId: string;
  onCreated: (versionId: string) => void;
}

const FORM_ID = 'create-tender-version';

export const CreateDraftDialog = ({
  open,
  onClose,
  projectId,
  onCreated,
}: ICreateDraftDialogProps) => {
  const create = useCreateTenderVersion(projectId);
  const [label, setLabel] = useState('');

  const submit = (event: FormEvent) => {
    event.preventDefault();
    create.mutate(
      { label: label.trim() || null },
      {
        onSuccess: (version) => {
          onCreated(version.id);
          onClose();
        },
      },
    );
  };

  return (
    <Dialog
      open={open}
      onClose={onClose}
      busy={create.isPending}
      title="Новый черновик версии"
      description="В состав попадут последние ревизии всех документов проекта. Состав можно поправить до заморозки."
      onExited={() => {
        setLabel('');
        create.reset();
      }}
      footer={
        <DialogActions>
          <Button onClick={onClose} disabled={create.isPending}>
            Отмена
          </Button>
          <Button
            type="submit"
            form={FORM_ID}
            variant="primary"
            loading={create.isPending}
            loadingLabel="Создаём…"
          >
            Создать черновик
          </Button>
        </DialogActions>
      }
    >
      <form id={FORM_ID} onSubmit={submit} className="flex flex-col gap-[var(--s-3)]">
        <label className="flex flex-col gap-[var(--s-2)] text-sm">
          Подпись (необязательно)
          <ClearableInput
            label="Подпись версии"
            value={label}
            maxLength={200}
            placeholder="Например: после замечаний экспертизы"
            wrapperClassName="w-full"
            onChange={(event) => setLabel(event.target.value)}
            onClear={() => setLabel('')}
          />
        </label>
        {create.error && (
          <p role="alert" className="text-sm text-danger">
            {errorMessage(extractCode(create.error))}
          </p>
        )}
      </form>
    </Dialog>
  );
};
