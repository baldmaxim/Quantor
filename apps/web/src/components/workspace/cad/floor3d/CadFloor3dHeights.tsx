'use client';

import type {
  CadHeightsRead,
  CadProjectLevelsRead,
  CadProjectLevelsWrite,
  CadSheetLevelsWrite,
} from '@quantor/api-client';
import { useState, type FC } from 'react';

import { Button } from '@/components/ui';
import { ClearableInput } from '@/components/ui/ClearableInput';
import {
  SHEET_LEVEL_SPECS,
  draftOf,
  heightSourceText,
  parseLevel,
  sheetOverridesOf,
  writeOfDraft,
  type LevelsDraft,
  type SheetLevelKey,
} from '@/lib/cad/floor3d-heights';

const PROJECT_SLAB_RANGE = [100, 1000] as const;

/** Текущее значение каждой высоты с источником. */
const valueOf = (heights: CadHeightsRead, key: SheetLevelKey) => {
  switch (key) {
    case 'floor_elevation_mm':
      return { value: heights.floor_elevation_mm, source: heights.floor_elevation_source };
    case 'floor_height_mm':
      return { value: heights.floor_height.value_mm, source: heights.floor_height.source };
    case 'slab_thickness_mm':
      return { value: heights.slab_thickness.value_mm, source: heights.slab_thickness.source };
    case 'door_height_mm':
      return { value: heights.door_height.value_mm, source: heights.door_height.source };
  }
};

const placeholderOf = (heights: CadHeightsRead, key: SheetLevelKey): string => {
  const base =
    key === 'floor_height_mm'
      ? heights.floor_height.default_mm
      : key === 'slab_thickness_mm'
        ? heights.slab_thickness.default_mm
        : key === 'door_height_mm'
          ? heights.door_height.default_mm
          : null;
  return base === null ? 'не определено' : String(base);
};

interface ISheetFormProps {
  readonly heights: CadHeightsRead;
  readonly saving: boolean;
  readonly onSave: (write: CadSheetLevelsWrite) => void;
}

/** Переопределения листа. Пустое поле снимает переопределение; запись несёт все четыре поля. */
const SheetLevelsForm: FC<ISheetFormProps> = ({ heights, saving, onSave }) => {
  const [draft, setDraft] = useState<LevelsDraft>(() => draftOf(sheetOverridesOf(heights)));
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    const result = writeOfDraft(draft);
    if ('error' in result) {
      setError(result.error);
      return;
    }
    setError(null);
    onSave(result.write);
  };

  return (
    <form
      className="flex min-w-0 flex-col gap-[var(--s-4)]"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      {SHEET_LEVEL_SPECS.map((spec) => {
        const current = valueOf(heights, spec.key);
        return (
          <label key={spec.key} className="flex min-w-0 flex-col gap-[var(--s-2)] text-xs text-muted">
            {spec.label}
            <ClearableInput
              label={spec.label}
              value={draft[spec.key]}
              inputMode="numeric"
              maxLength={7}
              placeholder={placeholderOf(heights, spec.key)}
              wrapperClassName="w-full"
              onChange={(event) => setDraft((prev) => ({ ...prev, [spec.key]: event.target.value }))}
              onClear={() => setDraft((prev) => ({ ...prev, [spec.key]: '' }))}
            />
            <span data-testid={`floor3d-value-${spec.key}`}>
              Действует:{' '}
              <span className="text-text">
                {current.value === null ? 'не определено' : `${current.value} мм`}
              </span>
              {current.value !== null && ` (${heightSourceText(current.source)})`}
            </span>
          </label>
        );
      })}
      {error !== null && (
        <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
          {error}
        </p>
      )}
      <Button type="submit" disabled={saving} className="self-start max-md:h-[44px]">
        Сохранить высоты листа
      </Button>
    </form>
  );
};

interface IProjectFormProps {
  readonly levels: CadProjectLevelsRead;
  readonly saving: boolean;
  readonly onSave: (write: CadProjectLevelsWrite) => void;
}

/** Толщина плиты по разрезу: одно значение на проект, лист разреза обязателен при числе. */
const ProjectSlabForm: FC<IProjectFormProps> = ({ levels, saving, onSave }) => {
  const [thickness, setThickness] = useState(
    levels.slab_thickness_mm === null ? '' : String(levels.slab_thickness_mm),
  );
  const [ref, setRef] = useState(levels.slab_source_ref ?? '');
  const [error, setError] = useState<string | null>(null);

  const submit = () => {
    const value = parseLevel(thickness, PROJECT_SLAB_RANGE);
    if (value === undefined) {
      setError(`Толщина плиты: целое число от ${PROJECT_SLAB_RANGE[0]} до ${PROJECT_SLAB_RANGE[1]}.`);
      return;
    }
    const source = ref.trim();
    if (value !== null && source === '') {
      setError('Укажите лист разреза, из которого взята толщина плиты.');
      return;
    }
    setError(null);
    onSave(value === null ? { slab_thickness_mm: null, slab_source_ref: null } : { slab_thickness_mm: value, slab_source_ref: source });
  };

  return (
    <form
      className="flex min-w-0 flex-col gap-[var(--s-4)]"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <label className="flex min-w-0 flex-col gap-[var(--s-2)] text-xs text-muted">
        Толщина плиты по разрезу, мм
        <ClearableInput
          label="Толщина плиты по разрезу, мм"
          value={thickness}
          inputMode="numeric"
          maxLength={4}
          wrapperClassName="w-full"
          onChange={(event) => setThickness(event.target.value)}
          onClear={() => setThickness('')}
        />
      </label>
      <label className="flex min-w-0 flex-col gap-[var(--s-2)] text-xs text-muted">
        Лист разреза
        <ClearableInput
          label="Лист разреза"
          value={ref}
          maxLength={200}
          placeholder="например, АР1.1 л. 45, разрез 4-4"
          wrapperClassName="w-full"
          onChange={(event) => setRef(event.target.value)}
          onClear={() => setRef('')}
        />
      </label>
      {error !== null && (
        <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
          {error}
        </p>
      )}
      <Button type="submit" disabled={saving} className="self-start max-md:h-[44px]">
        Сохранить толщину проекта
      </Button>
    </form>
  );
};

interface ICadFloor3dHeightsProps {
  readonly heights: CadHeightsRead;
  readonly elevationKnown: boolean;
  /** `undefined` - уровни проекта ещё читаются или не прочитаны. */
  readonly projectLevels: CadProjectLevelsRead | undefined;
  readonly sheetSaving: boolean;
  readonly projectSaving: boolean;
  /** Отказ последней записи. */
  readonly error: string | null;
  readonly onSaveSheet: (write: CadSheetLevelsWrite) => void;
  readonly onSaveProject: (write: CadProjectLevelsWrite) => void;
}

/**
 * Панель высот 3D-вида (ADR-0039 п. 4-5): отметка этажа, высота этажа, толщина плиты и высота двери
 * с источниками, переопределения листа и толщина плиты проекта из разреза. Вид величин не считает.
 */
export const CadFloor3dHeights: FC<ICadFloor3dHeightsProps> = ({
  heights,
  elevationKnown,
  projectLevels,
  sheetSaving,
  projectSaving,
  error,
  onSaveSheet,
  onSaveProject,
}) => {
  // Новое значение с сервера пересоздаёт форму: черновик не расходится с сохранённым.
  const sheetKey = JSON.stringify(sheetOverridesOf(heights));
  const projectKey = projectLevels
    ? `${projectLevels.slab_thickness_mm ?? ''}|${projectLevels.slab_source_ref ?? ''}|${projectLevels.updated_at ?? ''}`
    : 'loading';

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-5)]" data-testid="floor3d-heights">
      {!elevationKnown && (
        <p role="note" className="rounded-[var(--radius-sm)] bg-warning-soft px-[var(--s-4)] py-[var(--s-3)] text-xs text-warning">
          Отметка не определена — этаж построен от 0.
        </p>
      )}
      <section aria-label="Высоты листа" className="flex min-w-0 flex-col gap-[var(--s-3)]">
        <h4 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">Высоты листа</h4>
        <SheetLevelsForm key={sheetKey} heights={heights} saving={sheetSaving} onSave={onSaveSheet} />
        {heights.slab_thickness_sheet_ref != null && (
          <p className="text-xs text-muted [overflow-wrap:anywhere]">
            Толщина плиты взята из разреза проекта: {heights.slab_thickness_sheet_ref}.
          </p>
        )}
      </section>
      <section
        aria-label="Толщина плиты по разрезу (проект)"
        className="flex min-w-0 flex-col gap-[var(--s-3)]"
      >
        <h4 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">
          Толщина плиты по разрезу (проект)
        </h4>
        {projectLevels ? (
          <ProjectSlabForm
            key={projectKey}
            levels={projectLevels}
            saving={projectSaving}
            onSave={onSaveProject}
          />
        ) : (
          <p role="status" className="text-xs text-muted">
            Читаем уровни проекта…
          </p>
        )}
      </section>
      {error !== null && (
        <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
          {error}
        </p>
      )}
    </div>
  );
};
