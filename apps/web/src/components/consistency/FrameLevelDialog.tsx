'use client';

import type { FrameNodeOut, FrameNodePatch } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { Button, Dialog, DialogActions } from '@/components/ui';
import { ClearableInput } from '@/components/ui/ClearableInput';
import {
  elevationText,
  parseHeightMm,
  parseInteger,
  parseNumber,
  placeText,
} from '@/lib/consistency/building-frame';
import { useDeleteFrameNode, usePatchFrameNode } from '@/lib/consistency/building-frame-queries';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

/**
 * Правка уровня: номер, отметка, высота «пол - пол». Уходят только изменённые поля; правленое
 * сервер помечает «вручную», и пересборка его не трогает. Разные отметки листов показаны —
 * выбирает человек. Уровень, добавленный вручную, можно удалить.
 */

interface IDialogProps {
  readonly projectId: string;
  readonly level: FrameNodeOut;
  readonly onClose: () => void;
}

interface IForm {
  ordinal: string;
  elevation: string;
  heightMm: string;
}

const LABEL = 'flex min-w-0 flex-col gap-[var(--s-2)] text-xs text-muted';

const initial = (level: FrameNodeOut): IForm => ({
  ordinal: level.ordinal === null ? '' : String(level.ordinal),
  elevation: level.elevation_m === null ? '' : String(level.elevation_m),
  heightMm: level.height_m === null ? '' : String(Math.round(level.height_m * 1000)),
});

/** Изменённые поля; `null` — в форме ошибка. */
const buildPatch = (level: FrameNodeOut, form: IForm): FrameNodePatch | null => {
  const before = initial(level);
  const patch: FrameNodePatch = {};
  if (form.ordinal.trim() !== before.ordinal) {
    const parsed = parseInteger(form.ordinal);
    if (!parsed.ok) return null;
    patch.ordinal = parsed.value;
  }
  if (form.elevation.trim() !== before.elevation) {
    const parsed = parseNumber(form.elevation);
    if (!parsed.ok) return null;
    patch.elevation_m = parsed.value;
  }
  if (form.heightMm.trim() !== before.heightMm) {
    const parsed = parseHeightMm(form.heightMm);
    if (!parsed.ok) return null;
    patch.height_m = parsed.value;
  }
  return patch;
};

export const FrameLevelDialog: FC<IDialogProps> = ({ projectId, level, onClose }) => {
  const [form, setForm] = useState<IForm>(() => initial(level));
  const patchNode = usePatchFrameNode(projectId);
  const deleteNode = useDeleteFrameNode(projectId);
  const busy = patchNode.isPending || deleteNode.isPending;

  const set = (name: keyof IForm, value: string) =>
    setForm((current) => ({ ...current, [name]: value }));

  const patch = buildPatch(level, form);
  const changed = patch !== null && Object.keys(patch).length > 0;
  const error = patchNode.error ?? deleteNode.error;

  const save = () => {
    if (patch !== null && changed)
      patchNode.mutate({ id: level.id, patch }, { onSuccess: onClose });
  };

  return (
    <Dialog
      open
      onClose={onClose}
      busy={busy}
      title={`Уровень: ${level.code ?? ''}`}
      description={placeText(level.building, level.section)}
      footer={
        <>
          {error !== null && (
            <p role="alert" className="mr-auto text-sm text-danger">
              {extractMessage(error) ?? errorMessage(extractCode(error))}
            </p>
          )}
          <DialogActions>
            {level.origin === 'manual' && (
              <Button
                variant="danger"
                disabled={busy}
                onClick={() => deleteNode.mutate(level.id, { onSuccess: onClose })}
              >
                Удалить
              </Button>
            )}
            <Button onClick={onClose} disabled={busy}>
              Отмена
            </Button>
            <Button
              variant="primary"
              onClick={save}
              disabled={!changed}
              loading={patchNode.isPending}
            >
              Сохранить
            </Button>
          </DialogActions>
        </>
      }
    >
      <div className="flex flex-col gap-[var(--s-4)]">
        {level.elevation_values.length > 1 && (
          <p className="text-sm text-warning">
            На листах разные отметки: {level.elevation_values.map(elevationText).join('; ')}.
            Введите верную.
          </p>
        )}
        {level.elevation_sources.length > 0 && (
          <ul className="flex flex-col gap-[var(--s-1)] text-xs text-muted">
            {level.elevation_sources.map((source) => (
              <li
                key={`${source.passport_id}-${source.value_m}`}
                className="[overflow-wrap:anywhere]"
              >
                {elevationText(source.value_m)} — {source.file_name}, стр. {source.page_index + 1}
              </li>
            ))}
          </ul>
        )}
        <div className="grid gap-[var(--s-4)] sm:grid-cols-3">
          <div className={LABEL}>
            <span aria-hidden="true">Номер этажа</span>
            <ClearableInput
              label="Номер этажа"
              value={form.ordinal}
              inputMode="numeric"
              wrapperClassName="w-full"
              onChange={(event) => set('ordinal', event.target.value)}
              onClear={() => set('ordinal', '')}
            />
          </div>
          <div className={LABEL}>
            <span aria-hidden="true">Отметка, м</span>
            <ClearableInput
              label="Отметка, м"
              value={form.elevation}
              inputMode="decimal"
              wrapperClassName="w-full"
              onChange={(event) => set('elevation', event.target.value)}
              onClear={() => set('elevation', '')}
            />
          </div>
          <div className={LABEL}>
            <span aria-hidden="true">Высота, мм</span>
            <ClearableInput
              label="Высота, мм"
              value={form.heightMm}
              inputMode="numeric"
              wrapperClassName="w-full"
              onChange={(event) => set('heightMm', event.target.value)}
              onClear={() => set('heightMm', '')}
            />
          </div>
        </div>
        {patch === null && (
          <p className="text-sm text-danger">
            Номер — целое число, отметка — число в метрах, высота — целое число в мм.
          </p>
        )}
        <p className="text-xs text-muted">
          Пустая высота — выводится из отметки следующего уровня.
        </p>
      </div>
    </Dialog>
  );
};
