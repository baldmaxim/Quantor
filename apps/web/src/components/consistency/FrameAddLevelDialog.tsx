'use client';

import type { FrameNodeCreate } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { Button, Dialog, DialogActions } from '@/components/ui';
import { ClearableInput } from '@/components/ui/ClearableInput';
import { parseHeightMm, parseInteger, parseNumber } from '@/lib/consistency/building-frame';
import { useCreateFrameNode } from '@/lib/consistency/building-frame-queries';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

/**
 * Уровень, которого нет на планах (например, по ПЗ). Недостающие корпус и секция сервер создаёт
 * сам. Пустой корпус или секция — «не указан», как на листах без этих данных.
 */

interface IDialogProps {
  readonly projectId: string;
  readonly onClose: () => void;
}

type FieldName = 'building' | 'section' | 'code' | 'ordinal' | 'elevation' | 'heightMm';

const FIELDS: readonly { name: FieldName; label: string; mode?: 'numeric' | 'decimal' }[] = [
  { name: 'building', label: 'Корпус' },
  { name: 'section', label: 'Секция' },
  { name: 'code', label: 'Уровень, например «3 этаж» или «кровля»' },
  { name: 'ordinal', label: 'Номер этажа', mode: 'numeric' },
  { name: 'elevation', label: 'Отметка, м', mode: 'decimal' },
  { name: 'heightMm', label: 'Высота, мм', mode: 'numeric' },
];

const LABEL = 'flex min-w-0 flex-col gap-[var(--s-2)] text-xs text-muted';

type Form = Record<FieldName, string>;

const EMPTY: Form = {
  building: '',
  section: '',
  code: '',
  ordinal: '',
  elevation: '',
  heightMm: '',
};

const buildBody = (form: Form): FrameNodeCreate | null => {
  const ordinal = parseInteger(form.ordinal);
  const elevation = parseNumber(form.elevation);
  const height = parseHeightMm(form.heightMm);
  const code = form.code.trim();
  if (!code || !ordinal.ok || !elevation.ok || !height.ok) return null;
  return {
    kind: 'level',
    building: form.building.trim() || null,
    section: form.section.trim() || null,
    code,
    ordinal: ordinal.value,
    elevation_m: elevation.value,
    height_m: height.value,
  };
};

export const FrameAddLevelDialog: FC<IDialogProps> = ({ projectId, onClose }) => {
  const [form, setForm] = useState<Form>(EMPTY);
  const create = useCreateFrameNode(projectId);
  const body = buildBody(form);

  const set = (name: FieldName, value: string) =>
    setForm((current) => ({ ...current, [name]: value }));

  return (
    <Dialog
      open
      onClose={onClose}
      busy={create.isPending}
      title="Добавить уровень"
      description="Уровень попадёт в каркас кандидатом; в проверки — после подтверждения."
      footer={
        <>
          {create.isError && (
            <p role="alert" className="mr-auto text-sm text-danger">
              {extractMessage(create.error) ?? errorMessage(extractCode(create.error))}
            </p>
          )}
          <DialogActions>
            <Button onClick={onClose} disabled={create.isPending}>
              Отмена
            </Button>
            <Button
              variant="primary"
              disabled={body === null}
              loading={create.isPending}
              onClick={() => body && create.mutate(body, { onSuccess: onClose })}
            >
              Добавить
            </Button>
          </DialogActions>
        </>
      }
    >
      <div className="grid gap-[var(--s-4)] sm:grid-cols-2">
        {FIELDS.map(({ name, label, mode }) => (
          <div key={name} className={`${LABEL} ${name === 'code' ? 'sm:col-span-2' : ''}`}>
            <span aria-hidden="true">{label}</span>
            <ClearableInput
              label={label}
              value={form[name]}
              inputMode={mode}
              wrapperClassName="w-full"
              onChange={(event) => set(name, event.target.value)}
              onClear={() => set(name, '')}
            />
          </div>
        ))}
      </div>
    </Dialog>
  );
};
