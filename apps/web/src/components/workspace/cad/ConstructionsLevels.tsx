'use client';

import type { CadConstructionsRead, CadSheetLevelsWrite } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { Button } from '@/components/ui';
import { ClearableInput } from '@/components/ui/ClearableInput';
import { sourceLabel } from '@/lib/cad/construction-labels';

import { numberOrUndefined } from './ConstructionComputed';

type LevelKey = keyof CadSheetLevelsWrite;

interface ILevelSpec {
  readonly key: LevelKey;
  readonly label: string;
  readonly range: readonly [number, number];
}

const LEVELS: readonly ILevelSpec[] = [
  { key: 'floor_height_mm', label: 'Высота этажа, мм', range: [2000, 6000] },
  { key: 'slab_thickness_mm', label: 'Толщина плиты, мм', range: [100, 1000] },
  { key: 'door_height_mm', label: 'Высота двери, мм', range: [1500, 3500] },
];

interface IConstructionsLevelsProps {
  data: CadConstructionsRead;
  saving: boolean;
  onSave: (levels: CadSheetLevelsWrite) => void;
}

const valueOf = (data: CadConstructionsRead, key: LevelKey) =>
  key === 'floor_height_mm'
    ? data.heights.floor_height
    : key === 'slab_thickness_mm'
      ? data.heights.slab_thickness
      : data.heights.door_height;

/** Текст поля -> число или `null` (пусто = значение из результата расчёта); `undefined` - ошибка ввода. */
const parse = (raw: string, [min, max]: readonly [number, number]): number | null | undefined => {
  const text = raw.trim();
  if (text === '') return null;
  const value = Number(text.replace(',', '.'));
  return Number.isInteger(value) && value >= min && value <= max ? value : undefined;
};

/**
 * Высоты листа: отметка, высота этажа, толщина плиты и высота двери с источниками. Поле пусто -
 * действует значение из результата расчёта (подсказка в поле). Без высоты этажа объём стен не
 * считается: об этом сказано заметной строкой.
 */
export const ConstructionsLevels: FC<IConstructionsLevelsProps> = ({ data, saving, onSave }) => {
  const initial = Object.fromEntries(
    LEVELS.map(({ key }) => [key, data.sheet_levels[key] === null ? '' : String(data.sheet_levels[key])]),
  ) as Record<LevelKey, string>;
  const [draft, setDraft] = useState(initial);
  const [error, setError] = useState<string | null>(null);

  const { heights } = data;
  const missing = heights.floor_height.value_mm === null;

  const submit = () => {
    const write: CadSheetLevelsWrite = {};
    for (const spec of LEVELS) {
      const value = parse(draft[spec.key], spec.range);
      if (value === undefined) {
        setError(`${spec.label}: целое число от ${spec.range[0]} до ${spec.range[1]}.`);
        return;
      }
      write[spec.key] = value;
    }
    setError(null);
    onSave(write);
  };

  return (
    <section aria-label="Высоты листа" className="flex min-w-0 flex-col gap-[var(--s-3)]">
      <h4 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">Высоты листа</h4>
      {missing && (
        <p role="alert" className="text-xs font-medium text-danger">
          Нужна высота этажа: без неё объём стен не считается.
        </p>
      )}
      {heights.message !== null && <p className="text-xs text-muted">{heights.message}</p>}
      <p className="text-xs">
        <span className="text-muted">Отметка пола: </span>
        {numberOrUndefined(heights.floor_elevation_mm, 0, 'мм')}
        {heights.floor_elevation_mm !== null && (
          <span className="text-muted"> ({sourceLabel(heights.floor_elevation_source)})</span>
        )}
      </p>
      <form
        className="flex min-w-0 flex-col gap-[var(--s-3)]"
        onSubmit={(event) => {
          event.preventDefault();
          submit();
        }}
      >
        {LEVELS.map((spec) => {
          const level = valueOf(data, spec.key);
          return (
            <label key={spec.key} className="flex min-w-0 flex-col gap-[var(--s-2)] text-xs text-muted">
              {spec.label}
              <ClearableInput
                label={spec.label}
                value={draft[spec.key]}
                inputMode="numeric"
                maxLength={5}
                placeholder={level.default_mm === null ? 'не определено' : String(level.default_mm)}
                wrapperClassName="w-full"
                onChange={(event) => setDraft((current) => ({ ...current, [spec.key]: event.target.value }))}
                onClear={() => setDraft((current) => ({ ...current, [spec.key]: '' }))}
              />
              <span>
                Действует: {numberOrUndefined(level.value_mm, 0, 'мм')}
                {level.value_mm !== null && ` (${sourceLabel(level.source)})`}
              </span>
            </label>
          );
        })}
        {error !== null && (
          <p role="alert" className="text-xs text-danger">
            {error}
          </p>
        )}
        <Button type="submit" disabled={saving} className="self-start max-md:h-[44px]">
          Сохранить высоты
        </Button>
      </form>
      <p className="text-xs text-muted">
        Высота стены:{' '}
        <span className="text-text">{numberOrUndefined(heights.wall_height_mm, 0, 'мм')}</span>
        {heights.wall_height_mm !== null && ` (${sourceLabel(heights.wall_height_source)})`}
      </p>
    </section>
  );
};
