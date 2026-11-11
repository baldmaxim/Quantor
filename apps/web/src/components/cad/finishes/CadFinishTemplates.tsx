'use client';

import { useState, type FC } from 'react';

import type { CadFinishTemplateRead } from '@quantor/api-client';

import { Button, Skeleton } from '@/components/ui';
import { cadErrorText } from '@/lib/cad/errors';
import { useCadFinishTemplates, useDeleteCadFinishTemplate } from '@/lib/cad/finishes-queries';
import { ROOM_TYPE_LABELS } from '@/lib/cad/room-types';

import { CadFinishTemplateEditor } from './CadFinishTemplateEditor';

interface ICadFinishTemplatesProps {
  projectId: string;
  load: boolean;
}

/** `new` - форма нового шаблона; идентификатор - правка этого шаблона. */
type Editing = 'new' | string;

const layersCount = (template: CadFinishTemplateRead): number =>
  template.floor_layers.length + template.wall_layers.length + template.ceiling_layers.length;

/** Шаблоны отделки проекта: список, создание, правка, удаление с подтверждением. */
export const CadFinishTemplates: FC<ICadFinishTemplatesProps> = ({ projectId, load }) => {
  const list = useCadFinishTemplates(projectId, load);
  const remove = useDeleteCadFinishTemplate(projectId);
  const [editing, setEditing] = useState<Editing | null>(null);
  const [confirming, setConfirming] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  const templates = list.data ?? [];
  const editingTemplate =
    editing !== null && editing !== 'new'
      ? (templates.find((item) => item.id === editing) ?? null)
      : null;

  return (
    <section
      aria-label="Шаблоны отделки проекта"
      className="flex min-w-0 flex-col gap-[var(--s-3)]"
    >
      <h4 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">
        Шаблоны проекта
      </h4>

      {list.isPending && list.fetchStatus !== 'idle' && (
        <div
          role="status"
          aria-label="Загрузка шаблонов"
          className="flex flex-col gap-[var(--s-2)]"
        >
          <Skeleton className="h-[20px] w-[60%]" />
          <Skeleton className="h-[16px] w-[80%]" />
        </div>
      )}
      {list.isError && (
        <div role="alert" className="flex flex-col gap-[var(--s-2)] text-xs text-danger">
          <span>Не удалось загрузить шаблоны. {cadErrorText(list.error)}</span>
          <Button
            compact
            className="self-start max-md:h-[44px]"
            onClick={() => void list.refetch()}
          >
            Повторить
          </Button>
        </div>
      )}
      {list.isSuccess && templates.length === 0 && editing === null && (
        <p className="text-xs text-muted">Шаблонов пока нет.</p>
      )}

      {templates.length > 0 && (
        <ul className="m-0 flex list-none flex-col gap-[var(--s-2)] p-0">
          {templates.map((template) =>
            editing === template.id ? (
              <li key={template.id} className="min-w-0">
                <CadFinishTemplateEditor
                  projectId={projectId}
                  template={template}
                  templates={templates}
                  onClose={() => setEditing(null)}
                />
              </li>
            ) : (
              <li
                key={template.id}
                className="flex min-w-0 flex-col gap-[var(--s-2)] rounded-[var(--radius-sm)] border border-border p-[var(--s-3)]"
              >
                <span className="min-w-0 text-sm break-words">{template.name}</span>
                <span className="text-xs text-muted">
                  {template.room_types.length > 0
                    ? template.room_types.map((type) => ROOM_TYPE_LABELS[type]).join(', ')
                    : 'без автоназначения'}
                  {` · слоёв: ${layersCount(template)}`}
                  {template.wall_height_mm !== null && ` · стены ${template.wall_height_mm} мм`}
                </span>
                {confirming === template.id ? (
                  <div className="flex flex-wrap items-center gap-[var(--s-2)]" role="alert">
                    <span className="text-xs">Удалить шаблон?</span>
                    <Button
                      compact
                      variant="danger"
                      disabled={remove.isPending}
                      className="max-md:h-[44px]"
                      onClick={() => {
                        setError(null);
                        remove.mutate(template.id, {
                          onSuccess: () => setConfirming(null),
                          onError: (failure) => {
                            setConfirming(null);
                            setError(cadErrorText(failure));
                          },
                        });
                      }}
                    >
                      Удалить
                    </Button>
                    <Button compact className="max-md:h-[44px]" onClick={() => setConfirming(null)}>
                      Отмена
                    </Button>
                  </div>
                ) : (
                  <div className="flex flex-wrap gap-[var(--s-2)]">
                    <Button
                      compact
                      variant="ghost"
                      aria-label={`Изменить шаблон: ${template.name}`}
                      className="max-md:h-[44px]"
                      onClick={() => {
                        setError(null);
                        setEditing(template.id);
                      }}
                    >
                      Изменить
                    </Button>
                    <Button
                      compact
                      variant="ghost"
                      aria-label={`Удалить шаблон: ${template.name}`}
                      className="max-md:h-[44px]"
                      onClick={() => setConfirming(template.id)}
                    >
                      Удалить
                    </Button>
                  </div>
                )}
              </li>
            ),
          )}
        </ul>
      )}

      {error !== null && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}

      {editing === 'new' ? (
        <CadFinishTemplateEditor
          projectId={projectId}
          template={null}
          templates={templates}
          onClose={() => setEditing(null)}
        />
      ) : (
        editingTemplate === null &&
        editing === null && (
          <Button
            compact
            variant="primary"
            disabled={list.isError}
            className="self-start max-md:h-[44px]"
            onClick={() => {
              setError(null);
              setEditing('new');
            }}
          >
            Новый шаблон
          </Button>
        )
      )}
    </section>
  );
};
