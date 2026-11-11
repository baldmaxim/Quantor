'use client';

import { useState, type FC } from 'react';

import { Button, InspectorSection, Skeleton } from '@/components/ui';
import { cadErrorText } from '@/lib/cad/errors';
import {
  MAX_RISERS,
  draftOf,
  emptyRiser,
  entryOf,
  hasProblems,
  riserProblems,
  serializeDrafts,
  type IRiserDraft,
} from '@/lib/cad/risers';
import { sheetOf, useCadRisers, useSaveCadRisers } from '@/lib/cad/risers-queries';
import type { ICadViewParams } from '@/lib/cad/view-queries';

import { CadRiserRow } from './CadRiserRow';

interface IEditorProps {
  readonly params: ICadViewParams;
  readonly initial: readonly IRiserDraft[];
}

/**
 * Форма реестра. Живёт на копии строк сервера: ключ у родителя меняется при каждой записи,
 * поэтому после сохранения форма пересоздаётся из ответа.
 */
const CadRisersEditor: FC<IEditorProps> = ({ params, initial }) => {
  const save = useSaveCadRisers(sheetOf(params));
  const [rows, setRows] = useState<readonly IRiserDraft[]>(initial);
  const [touched, setTouched] = useState(false);

  const dirty = serializeDrafts(rows) !== serializeDrafts(initial);
  const problems = rows.map(riserProblems);
  const invalid = problems.some(hasProblems);

  const edit = (key: string, patch: Partial<IRiserDraft>) => {
    setRows((current) => current.map((row) => (row.key === key ? { ...row, ...patch } : row)));
  };

  const submit = () => {
    setTouched(true);
    if (invalid || save.isPending) return;
    save.mutate(rows.map(entryOf));
  };

  return (
    <form
      aria-label="Реестр стояков"
      className="flex min-w-0 flex-col gap-[var(--s-4)]"
      noValidate
      onSubmit={(event) => {
        event.preventDefault();
        submit();
      }}
    >
      {rows.length === 0 ? (
        <p className="text-xs text-muted" data-testid="cad-risers-empty">
          Реестр не задан: стояки по подписям шахт АР.
        </p>
      ) : (
        <ul className="m-0 flex min-w-0 list-none flex-col gap-[var(--s-3)] p-0">
          {rows.map((row, index) => (
            <CadRiserRow
              key={row.key}
              index={index}
              draft={row}
              problems={
                touched && hasProblems(problems[index] ?? {}) ? (problems[index] ?? null) : null
              }
              disabled={save.isPending}
              onChange={(patch) => edit(row.key, patch)}
              onRemove={() => {
                setRows((current) => current.filter((item) => item.key !== row.key));
              }}
            />
          ))}
        </ul>
      )}

      <Button
        disabled={save.isPending || rows.length >= MAX_RISERS}
        className="self-start max-md:h-[44px] max-md:w-full"
        onClick={() => {
          setRows((current) => [...current, emptyRiser()]);
        }}
      >
        Добавить строку
      </Button>
      {rows.length >= MAX_RISERS && (
        <p className="text-xs text-muted">Не больше {MAX_RISERS} записей.</p>
      )}

      <Button
        type="submit"
        variant="primary"
        loading={save.isPending}
        disabled={!dirty}
        className="self-start max-md:h-[44px] max-md:w-full"
      >
        Сохранить
      </Button>
      <p className="text-xs text-muted" role="note">
        После сохранения перестройте трассы: реестр входит в задание построения.
      </p>
      {touched && invalid && (
        <p role="alert" className="text-xs text-danger">
          Исправьте отмеченные поля.
        </p>
      )}
      {save.isError && (
        <p role="alert" className="text-xs text-danger [overflow-wrap:anywhere]">
          {cadErrorText(save.error)}
        </p>
      )}
    </form>
  );
};

interface ICadRisersPanelProps {
  /** Вид, к которому относится реестр: ревизия, страница и вид листа. */
  readonly parent: ICadViewParams;
}

/**
 * Раздел «Стояки»: реестр стояков листа по проекту ИОС (ADR-0041). Человек вводит или
 * подтверждает его; задание трасс берёт реестр входом, без реестра стояки идут по подписям
 * шахт АР. Реестр - данные человека, не обмер.
 */
export const CadRisersPanel: FC<ICadRisersPanelProps> = ({ parent }) => {
  const sheet = sheetOf(parent);
  const query = useCadRisers(sheet);

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-6)]" data-testid="cad-risers">
      <InspectorSection title="Стояки секции по проекту ИОС">
        {query.isPending && (
          <div
            role="status"
            aria-label="Загрузка реестра"
            className="flex flex-col gap-[var(--s-3)]"
          >
            <Skeleton className="h-[20px] w-[60%]" />
            <Skeleton className="h-[16px] w-[80%]" />
          </div>
        )}
        {query.isError && (
          <div role="alert" className="flex flex-col gap-[var(--s-3)] text-xs text-danger">
            <span>Не удалось загрузить реестр. {cadErrorText(query.error)}</span>
            <Button
              compact
              className="self-start max-md:h-[44px]"
              onClick={() => void query.refetch()}
            >
              Повторить
            </Button>
          </div>
        )}
        {query.data && (
          <CadRisersEditor
            // Ключ по листу и записи: после сохранения или смены листа форма читает ответ заново.
            key={`${sheet.revisionId}:${sheet.pageIndex}:${sheet.view}:${query.data.updated_at ?? ''}`}
            params={parent}
            initial={query.data.risers.map(draftOf)}
          />
        )}
        {query.data?.updated_at && (
          <p role="status" className="mt-[var(--s-3)] text-xs text-muted">
            Реестр сохранён {new Date(query.data.updated_at).toLocaleString('ru-RU')}.
          </p>
        )}
      </InspectorSection>
    </div>
  );
};
