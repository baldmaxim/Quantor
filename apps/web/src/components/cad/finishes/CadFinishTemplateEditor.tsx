'use client';

import { useState, type FC } from 'react';

import type { CadFinishTemplateRead } from '@quantor/api-client';

import { Button } from '@/components/ui';
import { ClearableInput } from '@/components/ui/ClearableInput';
import { cadErrorText } from '@/lib/cad/errors';
import {
  FINISH_PRESETS,
  TEXT_MAX,
  WALL_HEIGHT_MAX_MM,
  WALL_HEIGHT_MIN_MM,
  applyPreset,
  draftFromTemplate,
  emptyDraft,
  isDraftValid,
  layerProblems,
  templateProblems,
  toPatchBody,
  toWriteBody,
  type IFinishLayerDraft,
  type ITemplateDraft,
} from '@/lib/cad/finish-template';
import { useCreateCadFinishTemplate, useUpdateCadFinishTemplate } from '@/lib/cad/finishes-queries';
import { SURFACES, type FinishSurface } from '@/lib/cad/room-types';
import { extractCode } from '@/lib/errors';

import { CadFinishLayerRows } from './CadFinishLayerRows';
import { CadFinishRoomTypes } from './CadFinishRoomTypes';

interface ICadFinishTemplateEditorProps {
  projectId: string;
  /** Редактируемый шаблон; `null` - новый. */
  template: CadFinishTemplateRead | null;
  /** Все шаблоны проекта: нужны, чтобы показать занятые типы помещений. */
  templates: readonly CadFinishTemplateRead[];
  onClose: () => void;
}

const LABEL = 'flex min-w-0 flex-col gap-[var(--s-2)] text-xs text-muted';
const ERROR = 'text-xs text-danger';

const NAME_TAKEN = 'CAD_FINISH_TEMPLATE_NAME_TAKEN';
const ROOM_TYPE_TAKEN = 'CAD_FINISH_ROOM_TYPE_TAKEN';

/**
 * Форма шаблона отделки: название, типы помещений, высота стен, три поверхности со слоями.
 * Заготовки подставляют только работы и число слоёв; расход и толщины задаёт человек.
 * Ошибки 409 (название, тип помещения) - текстом у своего поля, остальные - у кнопок.
 */
export const CadFinishTemplateEditor: FC<ICadFinishTemplateEditorProps> = ({
  projectId,
  template,
  templates,
  onClose,
}) => {
  const create = useCreateCadFinishTemplate(projectId);
  const update = useUpdateCadFinishTemplate(projectId);
  const [draft, setDraft] = useState<ITemplateDraft>(() =>
    template === null ? emptyDraft() : draftFromTemplate(template),
  );
  const [touched, setTouched] = useState(false);
  const [failure, setFailure] = useState<{ code: string; text: string } | null>(null);

  const pending = create.isPending || update.isPending;
  const problems = templateProblems(draft);
  const edit = (patch: Partial<ITemplateDraft>) => {
    setDraft({ ...draft, ...patch });
    setFailure(null);
  };

  const submit = () => {
    setTouched(true);
    if (!isDraftValid(draft) || pending) return;
    setFailure(null);
    const onError = (error: unknown) =>
      setFailure({ code: extractCode(error), text: cadErrorText(error) });
    if (template === null) {
      create.mutate(toWriteBody(draft), { onSuccess: onClose, onError });
    } else {
      update.mutate(
        { id: template.id, patch: toPatchBody(draft) },
        { onSuccess: onClose, onError },
      );
    }
  };

  const nameError = touched ? problems.name : undefined;
  const heightError = touched ? problems.wallHeight : undefined;
  const hasLayerErrors =
    touched &&
    SURFACES.some((surface) =>
      draft[surface].some((layer) => Object.keys(layerProblems(layer)).length > 0),
    );
  const otherFailure =
    failure !== null && failure.code !== NAME_TAKEN && failure.code !== ROOM_TYPE_TAKEN
      ? failure.text
      : null;

  return (
    <form
      aria-label={template === null ? 'Новый шаблон отделки' : `Шаблон отделки: ${template.name}`}
      noValidate
      className="flex min-w-0 flex-col gap-[var(--s-5)] rounded-[var(--radius-sm)] border border-border-strong p-[var(--s-4)]"
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      <label className={LABEL}>
        Название шаблона
        <ClearableInput
          label="Название шаблона"
          value={draft.name}
          maxLength={TEXT_MAX}
          disabled={pending}
          aria-invalid={nameError !== undefined || failure?.code === NAME_TAKEN}
          wrapperClassName="w-full"
          onChange={(event) => edit({ name: event.target.value })}
          onClear={() => edit({ name: '' })}
        />
        {nameError !== undefined && <span className={ERROR}>{nameError}</span>}
        {failure?.code === NAME_TAKEN && <span className={ERROR}>{failure.text}</span>}
      </label>

      <div className="flex min-w-0 flex-col gap-[var(--s-2)]">
        <CadFinishRoomTypes
          selected={draft.roomTypes}
          onChange={(roomTypes) => edit({ roomTypes })}
          templates={templates}
          editingId={template?.id ?? null}
          disabled={pending}
        />
        {failure?.code === ROOM_TYPE_TAKEN && (
          <span role="alert" className={ERROR}>
            {failure.text}
          </span>
        )}
      </div>

      <label className={LABEL}>
        Высота стен, мм (необязательно)
        <ClearableInput
          label="Высота стен, мм"
          value={draft.wallHeight}
          inputMode="numeric"
          maxLength={4}
          disabled={pending}
          aria-invalid={heightError !== undefined}
          wrapperClassName="w-full"
          onChange={(event) => edit({ wallHeight: event.target.value })}
          onClear={() => edit({ wallHeight: '' })}
        />
        <span>
          До подвесного потолка; пусто — до низа перекрытия минус слои пола. От {WALL_HEIGHT_MIN_MM}{' '}
          до {WALL_HEIGHT_MAX_MM} мм.
        </span>
        {heightError !== undefined && <span className={ERROR}>{heightError}</span>}
      </label>

      <label className="flex min-h-[44px] cursor-pointer items-center gap-[var(--s-3)] text-xs">
        <input
          type="checkbox"
          aria-label="Включать откосы дверей в стены"
          checked={draft.wallsIncludeReveals}
          disabled={pending}
          onChange={(event) => edit({ wallsIncludeReveals: event.target.checked })}
          className="h-[18px] w-[18px] shrink-0 accent-[var(--accent)]"
        />
        Включать откосы дверей в стены
      </label>

      <div className="flex min-w-0 flex-col gap-[var(--s-2)]">
        <span className="text-xs font-semibold">Заготовки слоёв</span>
        <div className="flex flex-wrap gap-[var(--s-2)]">
          {FINISH_PRESETS.map((preset) => (
            <Button
              key={preset.id}
              compact
              disabled={pending}
              className="max-md:h-[44px]"
              onClick={() => edit(applyPreset(draft, preset.id))}
            >
              {preset.title}
            </Button>
          ))}
        </div>
        <p className="text-xs text-muted">
          Заготовка заменяет слои: подставляет работы, число слоёв и основания стен. Расход, единицы
          и толщины задайте сами.
        </p>
      </div>

      {SURFACES.map((surface: FinishSurface) => (
        <CadFinishLayerRows
          key={surface}
          surface={surface}
          layers={draft[surface]}
          showProblems={touched}
          disabled={pending}
          onChange={(layers: readonly IFinishLayerDraft[]) => edit({ [surface]: layers })}
        />
      ))}

      {hasLayerErrors && (
        <p role="alert" className={ERROR}>
          Исправьте отмеченные поля слоёв.
        </p>
      )}
      {otherFailure !== null && (
        <p role="alert" className={ERROR}>
          {otherFailure}
        </p>
      )}

      <div className="flex flex-wrap gap-[var(--s-2)]">
        <Button type="submit" variant="primary" disabled={pending} className="max-md:h-[44px]">
          {template === null ? 'Создать шаблон' : 'Сохранить'}
        </Button>
        <Button disabled={pending} className="max-md:h-[44px]" onClick={onClose}>
          Отмена
        </Button>
      </div>
    </form>
  );
};
