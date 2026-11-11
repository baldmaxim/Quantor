'use client';

import type { FC } from 'react';

import { Button } from '@/components/ui';
import { ClearableInput } from '@/components/ui/ClearableInput';
import {
  MAX_LAYERS,
  TEXT_MAX,
  UNIT_MAX,
  emptyLayer,
  layerProblems,
  type IFinishLayerDraft,
  type ILayerProblems,
} from '@/lib/cad/finish-template';
import {
  FINISH_BASES,
  FINISH_BASE_LABELS,
  SURFACE_LABELS,
  type FinishBase,
  type FinishSurface,
} from '@/lib/cad/room-types';

interface ICadFinishLayerRowsProps {
  surface: FinishSurface;
  layers: readonly IFinishLayerDraft[];
  onChange: (layers: readonly IFinishLayerDraft[]) => void;
  /** Показывать ошибки полей: после первой попытки сохранить. */
  showProblems: boolean;
  disabled?: boolean;
}

const LABEL = 'flex min-w-0 flex-col gap-[var(--s-1)] text-micro text-muted';
const ERROR = 'text-micro text-danger';

interface IFieldProps {
  label: string;
  title: string;
  value: string;
  onChange: (value: string) => void;
  problem?: string;
  maxLength?: number;
  numeric?: boolean;
  disabled?: boolean;
}

/** Поле строки слоя: подпись над полем, крестик очистки, ошибка под полем. */
const Field: FC<IFieldProps> = ({
  label,
  title,
  value,
  onChange,
  problem,
  maxLength,
  numeric = false,
  disabled = false,
}) => (
  <label className={LABEL}>
    {title}
    <ClearableInput
      label={label}
      value={value}
      maxLength={maxLength}
      inputMode={numeric ? 'decimal' : undefined}
      disabled={disabled}
      aria-invalid={problem !== undefined}
      wrapperClassName="w-full"
      onChange={(event) => onChange(event.target.value)}
      onClear={() => onChange('')}
    />
    {problem !== undefined && <span className={ERROR}>{problem}</span>}
  </label>
);

/** Основания слоя стен: чипы-флажки; ни одного или все - «все основания». */
const BasesChips: FC<{
  name: string;
  bases: readonly FinishBase[];
  onChange: (bases: readonly FinishBase[]) => void;
}> = ({ name, bases, onChange }) => (
  <fieldset className="m-0 flex min-w-0 flex-col gap-[var(--s-1)] border-0 p-0">
    <legend className="mb-[var(--s-1)] p-0 text-micro text-muted">
      Основания (ни одного — все)
    </legend>
    <div className="flex flex-wrap gap-[var(--s-2)]">
      {FINISH_BASES.map((base) => {
        const checked = bases.includes(base);
        return (
          <label
            key={base}
            className={`flex min-h-[44px] min-w-[44px] cursor-pointer items-center justify-center gap-[var(--s-2)] rounded-[var(--radius-sm)] border px-[var(--s-3)] text-xs ${
              checked ? 'border-accent text-text' : 'border-border text-muted'
            }`}
          >
            <input
              type="checkbox"
              aria-label={`${FINISH_BASE_LABELS[base]}: ${name}`}
              checked={checked}
              onChange={() =>
                onChange(checked ? bases.filter((item) => item !== base) : [...bases, base])
              }
              className="h-[18px] w-[18px] accent-[var(--accent)]"
            />
            {FINISH_BASE_LABELS[base]}
          </label>
        );
      })}
    </div>
  </fieldset>
);

const ICON_BUTTON = 'min-w-[44px] max-md:h-[44px]';

/**
 * Слои одной поверхности шаблона: работа, материал, раз, толщина, расход, единица, «на мм»;
 * вверх/вниз/удалить; не больше 20 слоёв. Все числа вводит человек - заготовки их не подставляют.
 */
export const CadFinishLayerRows: FC<ICadFinishLayerRowsProps> = ({
  surface,
  layers,
  onChange,
  showProblems,
  disabled = false,
}) => {
  const title = SURFACE_LABELS[surface];

  const patch = (key: string, change: Partial<IFinishLayerDraft>) =>
    onChange(layers.map((layer) => (layer.key === key ? { ...layer, ...change } : layer)));

  const move = (index: number, step: -1 | 1) => {
    const target = index + step;
    if (target < 0 || target >= layers.length) return;
    const next = [...layers];
    const [item] = next.splice(index, 1);
    if (item === undefined) return;
    next.splice(target, 0, item);
    onChange(next);
  };

  return (
    <fieldset
      className="m-0 flex min-w-0 flex-col gap-[var(--s-3)] border-0 p-0"
      disabled={disabled}
    >
      <legend className="mb-[var(--s-2)] flex w-full items-baseline justify-between gap-[var(--s-3)] p-0 text-xs font-semibold">
        <span>{title}</span>
        <span className="font-normal text-muted">
          слоёв: {layers.length} из {MAX_LAYERS}
        </span>
      </legend>

      {layers.length === 0 && <p className="text-xs text-muted">Слоёв нет.</p>}

      {layers.map((layer, index) => {
        const problems: ILayerProblems = showProblems ? layerProblems(layer) : {};
        const name = `${title}, слой ${index + 1}`;
        return (
          <div
            key={layer.key}
            role="group"
            aria-label={name}
            className="flex min-w-0 flex-col gap-[var(--s-2)] rounded-[var(--radius-sm)] border border-border p-[var(--s-3)]"
          >
            <Field
              label={`Работа: ${name}`}
              title="Работа"
              value={layer.work}
              maxLength={TEXT_MAX}
              problem={problems.work}
              onChange={(work) => patch(layer.key, { work })}
            />
            <Field
              label={`Материал: ${name}`}
              title="Материал"
              value={layer.material}
              maxLength={TEXT_MAX}
              onChange={(material) => patch(layer.key, { material })}
            />
            <div className="grid min-w-0 grid-cols-2 gap-[var(--s-2)]">
              <Field
                label={`Раз: ${name}`}
                title="Раз"
                value={layer.coats}
                numeric
                maxLength={1}
                problem={problems.coats}
                onChange={(coats) => patch(layer.key, { coats })}
              />
              <Field
                label={`Толщина, мм: ${name}`}
                title="Толщина, мм"
                value={layer.thickness}
                numeric
                maxLength={7}
                problem={problems.thickness}
                onChange={(thickness) => patch(layer.key, { thickness })}
              />
              <Field
                label={`Расход: ${name}`}
                title="Расход"
                value={layer.consumption}
                numeric
                maxLength={10}
                problem={problems.consumption}
                onChange={(consumption) => patch(layer.key, { consumption })}
              />
              <Field
                label={`Единица расхода: ${name}`}
                title="Ед. (кг, л, шт)"
                value={layer.unit}
                maxLength={UNIT_MAX}
                problem={problems.unit}
                onChange={(unit) => patch(layer.key, { unit })}
              />
            </div>
            <label className="flex min-h-[44px] cursor-pointer items-center gap-[var(--s-3)] text-xs">
              <input
                type="checkbox"
                aria-label={`Расход на мм: ${name}`}
                checked={layer.perMm}
                onChange={(event) => patch(layer.key, { perMm: event.target.checked })}
                className="h-[18px] w-[18px] accent-[var(--accent)]"
              />
              Расход на мм толщины (на м² · мм)
            </label>
            {surface === 'walls' && (
              <BasesChips
                name={name}
                bases={layer.bases}
                onChange={(bases) => patch(layer.key, { bases })}
              />
            )}
            <div className="flex flex-wrap gap-[var(--s-2)]">
              <Button
                compact
                variant="ghost"
                aria-label={`Вверх: ${name}`}
                disabled={index === 0}
                className={ICON_BUTTON}
                onClick={() => move(index, -1)}
              >
                Вверх
              </Button>
              <Button
                compact
                variant="ghost"
                aria-label={`Вниз: ${name}`}
                disabled={index === layers.length - 1}
                className={ICON_BUTTON}
                onClick={() => move(index, 1)}
              >
                Вниз
              </Button>
              <Button
                compact
                variant="ghost"
                aria-label={`Удалить: ${name}`}
                className={ICON_BUTTON}
                onClick={() => onChange(layers.filter((item) => item.key !== layer.key))}
              >
                Удалить
              </Button>
            </div>
          </div>
        );
      })}

      <Button
        compact
        aria-label={`Добавить слой: ${title}`}
        disabled={layers.length >= MAX_LAYERS}
        className="self-start max-md:h-[44px]"
        onClick={() => onChange([...layers, emptyLayer()])}
      >
        Добавить слой
      </Button>
    </fieldset>
  );
};
