'use client';

import type { SheetPassportOut, SheetPassportPatch } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { Button, Dialog, DialogActions } from '@/components/ui';
import { ClearableInput } from '@/components/ui/ClearableInput';
import {
  SHEET_KIND_LABELS,
  SHEET_KIND_VALUES,
  STAGE_VALUES,
} from '@/lib/consistency/sheet-passports';
import { usePatchPassport } from '@/lib/consistency/sheet-passport-queries';
import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

/**
 * Правка паспорта листа. Уходят только изменённые поля; правленое поле сервер помечает «вручную».
 * Раздел выбирается из марок, уже встреченных в комплекте: свободного ввода нет.
 */

interface IEditDialogProps {
  readonly projectId: string;
  readonly row: SheetPassportOut;
  readonly marks: readonly string[];
  readonly onClose: () => void;
}

type TextField = 'building' | 'section' | 'level_from' | 'level_to' | 'sheet_number' | 'title';

interface IForm {
  section_mark: string;
  sheet_kind: string;
  stage: string;
  building: string;
  section: string;
  level_from: string;
  level_to: string;
  elevation_m: string;
  sheet_number: string;
  title: string;
}

const TEXT_FIELDS: readonly { name: TextField; label: string }[] = [
  { name: 'building', label: 'Корпус' },
  { name: 'section', label: 'Секция' },
  { name: 'level_from', label: 'Этаж от' },
  { name: 'level_to', label: 'Этаж до' },
  { name: 'sheet_number', label: '№ листа' },
  { name: 'title', label: 'Заголовок' },
];

const LABEL = 'flex min-w-0 flex-col gap-[var(--s-2)] text-xs text-muted';
const SELECT =
  'h-[var(--h-ctl)] w-full rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:text-sm max-md:h-[44px]';

const initialForm = (row: SheetPassportOut): IForm => ({
  section_mark: row.section_mark ?? '',
  sheet_kind: row.sheet_kind ?? '',
  stage: row.stage ?? '',
  building: row.building ?? '',
  section: row.section ?? '',
  level_from: row.level_from ?? '',
  level_to: row.level_to ?? '',
  elevation_m: row.elevation_m === null ? '' : String(row.elevation_m),
  sheet_number: row.sheet_number ?? '',
  title: row.title ?? '',
});

type ElevationResult = { ok: true; value: number | null } | { ok: false };

const parseElevation = (text: string): ElevationResult => {
  const clean = text.trim().replace(',', '.');
  if (clean === '') {
    return { ok: true, value: null };
  }
  const value = Number(clean);
  return Number.isFinite(value) ? { ok: true, value } : { ok: false };
};

/** Изменённые поля формы относительно строки; `null` — отметка не число. */
const buildPatch = (row: SheetPassportOut, form: IForm): SheetPassportPatch | null => {
  const before = initialForm(row);
  const patch: SheetPassportPatch = {};
  const text = (value: string): string | null => value.trim() || null;

  if (form.section_mark !== before.section_mark) patch.section_mark = text(form.section_mark);
  if (form.sheet_kind !== before.sheet_kind) patch.sheet_kind = text(form.sheet_kind);
  if (form.stage !== before.stage) patch.stage = text(form.stage);
  for (const { name } of TEXT_FIELDS) {
    if (form[name].trim() !== before[name]) patch[name] = text(form[name]);
  }
  if (form.elevation_m.trim() !== before.elevation_m) {
    const parsed = parseElevation(form.elevation_m);
    if (!parsed.ok) {
      return null;
    }
    patch.elevation_m = parsed.value;
  }
  return patch;
};

export const SheetPassportEditDialog: FC<IEditDialogProps> = ({
  projectId,
  row,
  marks,
  onClose,
}) => {
  const [form, setForm] = useState<IForm>(() => initialForm(row));
  const patchPassport = usePatchPassport(projectId);

  const set = (name: keyof IForm, value: string) =>
    setForm((current) => ({ ...current, [name]: value }));

  const patch = buildPatch(row, form);
  const badElevation = patch === null;
  const changed = patch !== null && Object.keys(patch).length > 0;
  // Текущая марка строки всегда в списке, даже если её нет среди встреченных.
  const markOptions =
    row.section_mark && !marks.includes(row.section_mark) ? [row.section_mark, ...marks] : marks;

  const save = () => {
    if (patch === null || !changed) {
      return;
    }
    patchPassport.mutate({ id: row.id, patch }, { onSuccess: onClose });
  };

  return (
    <Dialog
      open
      onClose={onClose}
      busy={patchPassport.isPending}
      title="Правка листа"
      description={`${row.file_name}, стр. ${row.page_index + 1}`}
      footer={
        <>
          {patchPassport.isError && (
            <p role="alert" className="mr-auto text-sm text-danger">
              {extractMessage(patchPassport.error) ??
                errorMessage(extractCode(patchPassport.error))}
            </p>
          )}
          <DialogActions>
            <Button onClick={onClose} disabled={patchPassport.isPending}>
              Отмена
            </Button>
            <Button
              variant="primary"
              onClick={save}
              disabled={!changed}
              loading={patchPassport.isPending}
            >
              Сохранить
            </Button>
          </DialogActions>
        </>
      }
    >
      <div className="grid gap-[var(--s-4)] sm:grid-cols-2">
        <label className={LABEL}>
          Раздел
          <select
            className={SELECT}
            value={form.section_mark}
            onChange={(event) => set('section_mark', event.target.value)}
          >
            <option value="">—</option>
            {markOptions.map((mark) => (
              <option key={mark} value={mark}>
                {mark}
              </option>
            ))}
          </select>
        </label>
        <label className={LABEL}>
          Тип листа
          <select
            className={SELECT}
            value={form.sheet_kind}
            onChange={(event) => set('sheet_kind', event.target.value)}
          >
            <option value="">—</option>
            {SHEET_KIND_VALUES.map((kind) => (
              <option key={kind} value={kind}>
                {SHEET_KIND_LABELS[kind]}
              </option>
            ))}
          </select>
        </label>
        <label className={LABEL}>
          Стадия
          <select
            className={SELECT}
            value={form.stage}
            onChange={(event) => set('stage', event.target.value)}
          >
            <option value="">—</option>
            {STAGE_VALUES.map((stage) => (
              <option key={stage} value={stage}>
                {stage}
              </option>
            ))}
          </select>
        </label>
        {TEXT_FIELDS.map(({ name, label }) => (
          <div key={name} className={`${LABEL} ${name === 'title' ? 'sm:col-span-2' : ''}`}>
            <span aria-hidden="true">{label}</span>
            <ClearableInput
              label={label}
              value={form[name]}
              wrapperClassName="w-full"
              onChange={(event) => set(name, event.target.value)}
              onClear={() => set(name, '')}
            />
          </div>
        ))}
        <div className={LABEL}>
          <span aria-hidden="true">Отметка, м</span>
          <ClearableInput
            label="Отметка, м"
            value={form.elevation_m}
            inputMode="decimal"
            wrapperClassName="w-full"
            aria-invalid={badElevation || undefined}
            onChange={(event) => set('elevation_m', event.target.value)}
            onClear={() => set('elevation_m', '')}
          />
          {badElevation && <span className="text-danger">Отметка должна быть числом</span>}
        </div>
      </div>
    </Dialog>
  );
};
