'use client';

import type { CadConstructionProps, CadConstructionRead } from '@quantor/api-client';
import { useMemo, useState, type FC, type ReactNode } from 'react';

import { Button } from '@/components/ui';
import { ClearableInput } from '@/components/ui/ClearableInput';
import {
  BRICK_LAYOUT_LABELS,
  BRICK_LAYOUTS,
  KIND_LABELS,
  MATERIAL_LABELS,
  MATERIALS,
  MORTAR_LABELS,
  MORTARS,
  PURPOSE_LABELS,
  PURPOSES,
  isMonolith,
  showBlockSize,
  showBrickLayout,
} from '@/lib/cad/construction-labels';
import {
  NUMBER_LABELS,
  TEXT_MAX,
  draftOf,
  isEmptyPatch,
  patchOfDraft,
  propsOfDraft,
  samePropsDraft,
  type IPropsDraft,
  type NumberField,
  type SelectField,
  type TextField,
} from '@/lib/cad/construction-props';

interface IConstructionPropsFormProps {
  construction: CadConstructionRead;
  /** Конструкций того же вида и номинала на листе, включая эту. */
  groupCount: number;
  saving: boolean;
  onSave: (props: CadConstructionProps) => void;
  onBulk: (patch: CadConstructionProps) => void;
  onAccept: (accepted: boolean) => void;
}

const LABEL = 'flex min-w-0 flex-col gap-[var(--s-2)] text-xs text-muted';
const SELECT =
  'h-[var(--h-ctl)] w-full rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:text-sm max-md:h-[44px]';

interface ISelectProps {
  label: string;
  value: string;
  empty: string;
  options: readonly { value: string; label: string }[];
  onChange: (value: string) => void;
}

const Select: FC<ISelectProps> = ({ label, value, empty, options, onChange }) => (
  <label className={LABEL}>
    {label}
    <select value={value} onChange={(event) => onChange(event.target.value)} className={SELECT}>
      <option value="">{empty}</option>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  </label>
);

const options = <T extends string>(keys: readonly T[], labels: Readonly<Record<T, string>>) =>
  keys.map((key) => ({ value: key, label: labels[key] }));

/**
 * Параметры конструкции: материал, блок, шов, назначение, огнестойкость и переопределения.
 * Все поля необязательны; пустое поле - «не задано». Поля кирпича и блока показываются по смыслу
 * материала, у монолита - класс бетона. Валидация диапазонов - до запроса, величины считает сервер.
 */
export const ConstructionPropsForm: FC<IConstructionPropsFormProps> = ({
  construction,
  groupCount,
  saving,
  onSave,
  onBulk,
  onAccept,
}) => {
  const stored = useMemo(() => draftOf(construction.props), [construction.props]);
  const [draft, setDraft] = useState<IPropsDraft>(stored);

  const kind = construction.kind;
  const monolith = isMonolith(kind);
  const masonry = kind === 'masonry';
  const fromDocument = construction.material;
  const material = draft.material === '' ? null : (draft.material as keyof typeof MATERIAL_LABELS);
  const { props, error } = propsOfDraft(draft);
  const dirty = !samePropsDraft(draft, stored);
  const patch = patchOfDraft(draft, stored);

  const setSelect = (key: SelectField, value: string) =>
    setDraft((current) => ({ ...current, [key]: value }));
  const setText = (key: TextField, value: string) =>
    setDraft((current) => ({ ...current, text: { ...current.text, [key]: value } }));
  const setNumber = (key: NumberField, value: string) =>
    setDraft((current) => ({ ...current, numbers: { ...current.numbers, [key]: value } }));

  const text = (key: TextField, label: string, placeholder?: string): ReactNode => (
    <label className={LABEL}>
      {label}
      <ClearableInput
        label={label}
        value={draft.text[key]}
        maxLength={TEXT_MAX[key]}
        placeholder={placeholder}
        wrapperClassName="w-full"
        onChange={(event) => setText(key, event.target.value)}
        onClear={() => setText(key, '')}
      />
    </label>
  );

  const number = (key: NumberField, label: string = NUMBER_LABELS[key]): ReactNode => (
    <label className={LABEL}>
      {label}
      <ClearableInput
        label={label}
        value={draft.numbers[key]}
        inputMode="numeric"
        maxLength={5}
        wrapperClassName="w-full"
        onChange={(event) => setNumber(key, event.target.value)}
        onClear={() => setNumber(key, '')}
      />
    </label>
  );

  const nominal = construction.thickness_nominal_mm;
  const documentMaterial =
    fromDocument.source === 'document' && fromDocument.value !== null ? fromDocument.value : null;
  // Материал из документа в поле не подставляется: пустое поле - «человек не выбирал».
  let materialEmpty = 'Не задан';
  if (documentMaterial !== null) materialEmpty = `По документу: ${MATERIAL_LABELS[documentMaterial]}`;
  else if (monolith) materialEmpty = `${MATERIAL_LABELS.monolith_concrete} (по умолчанию)`;

  const bulkLabel = `Применить ко всем: ${KIND_LABELS[kind]} ${
    nominal === null ? 'без номинала' : `${nominal} мм`
  } на листе (${groupCount} шт.)`;

  return (
    <form
      aria-label="Параметры конструкции"
      className="flex min-w-0 flex-col gap-[var(--s-4)]"
      onSubmit={(event) => {
        event.preventDefault();
        if (error === null) onSave(props);
      }}
    >
      <h4 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">
        Параметры
      </h4>

      <Select
        label="Материал"
        value={draft.material}
        empty={materialEmpty}
        options={options(MATERIALS, MATERIAL_LABELS)}
        onChange={(value) => setSelect('material', value)}
      />
      {text('material_note', 'Примечание к материалу')}
      {masonry && text('density_grade', 'Марка по плотности', 'D500')}
      {text('strength_class', monolith ? 'Класс бетона' : 'Класс прочности', monolith ? 'B25' : 'B2,5')}

      {showBlockSize(kind, material) && (
        <div className="grid grid-cols-3 gap-[var(--s-3)]" role="group" aria-label="Размер блока Д×Ш×В">
          {number('block_length_mm', 'Длина, мм')}
          {number('block_width_mm', 'Ширина, мм')}
          {number('block_height_mm', 'Высота, мм')}
        </div>
      )}
      {showBrickLayout(kind, material) && (
        <Select
          label="Кладка в кирпичах"
          value={draft.brick_layout}
          empty="Не задана"
          options={options(BRICK_LAYOUTS, BRICK_LAYOUT_LABELS)}
          onChange={(value) => setSelect('brick_layout', value)}
        />
      )}
      {masonry && (
        <>
          <Select
            label="Раствор или клей"
            value={draft.mortar}
            empty="Не задан"
            options={options(MORTARS, MORTAR_LABELS)}
            onChange={(value) => setSelect('mortar', value)}
          />
          {number('joint_mm')}
        </>
      )}

      {text('reinforcement', 'Армирование')}
      <Select
        label="Назначение"
        value={draft.purpose}
        empty="Не задано"
        options={options(PURPOSES, PURPOSE_LABELS)}
        onChange={(value) => setSelect('purpose', value)}
      />
      {text('fire_rating', 'Огнестойкость EI', 'EI 150')}
      {number('sound_rw_db')}
      {number('height_override_mm')}
      {number('thickness_override_mm')}

      <label className="flex min-h-[44px] items-center gap-[var(--s-3)] text-sm">
        <input
          type="checkbox"
          checked={draft.count_openings}
          onChange={(event) => setDraft((current) => ({ ...current, count_openings: event.target.checked }))}
          className="size-5 shrink-0"
        />
        Учитывать надпроёмные части
      </label>

      {text('note', 'Примечание')}

      {error !== null && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}

      <div className="flex min-w-0 flex-col gap-[var(--s-3)]">
        <Button
          type="submit"
          variant="primary"
          disabled={saving || error !== null}
          className="self-start max-md:h-[44px]"
        >
          Сохранить
        </Button>
        <Button
          type="button"
          disabled={saving || patch.error !== null || isEmptyPatch(patch.props) || groupCount === 0}
          className="h-auto min-h-[var(--h-ctl)] self-start py-[var(--s-2)] text-left whitespace-normal max-md:min-h-[44px]"
          onClick={() => onBulk(patch.props)}
        >
          {bulkLabel}
        </Button>
        <Button
          type="button"
          disabled={saving || dirty}
          className="self-start max-md:h-[44px]"
          onClick={() => onAccept(!construction.accepted)}
        >
          {construction.accepted ? 'Снять принятие' : 'Принять'}
        </Button>
        {dirty && (
          <p className="text-xs text-muted">Чтобы принять конструкцию, сначала сохраните изменения.</p>
        )}
      </div>
    </form>
  );
};
