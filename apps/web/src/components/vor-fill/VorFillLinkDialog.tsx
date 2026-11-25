'use client';

import type { CadVorItemRead } from '@quantor/api-client';
import { useEffect, useState, type FC } from 'react';

import { Button, Dialog, DialogActions } from '@/components/ui';
import { ClearableInput } from '@/components/ui/ClearableInput';
import { suggestReasonsText, vorItemQuantity, vorItemTitle } from '@/lib/cad/vor';
import {
  useCadVorItems,
  useCadVorSuggest,
  usePutCadVorLinks,
  vorErrorText,
  VOR_ITEMS_LIMIT,
} from '@/lib/cad/vor-queries';

interface IDialogProps {
  readonly projectId: string;
  readonly documentId: string;
  readonly groupKey: string;
  readonly title: string;
  /** Строки ВОР, уже связанные с объектом. */
  readonly linked: readonly CadVorItemRead[];
  readonly onClose: () => void;
}

const SEARCH_DELAY_MS = 300;

const ItemRow: FC<{
  item: CadVorItemRead;
  checked: boolean;
  note?: string;
  onToggle: (item: CadVorItemRead) => void;
}> = ({ item, checked, note, onToggle }) => (
  <li>
    <label className="flex min-h-[44px] cursor-pointer items-start gap-[var(--s-3)] py-[var(--s-2)] text-xs md:min-h-[32px]">
      <input
        type="checkbox"
        checked={checked}
        onChange={() => onToggle(item)}
        className="mt-[2px] size-5 shrink-0"
      />
      <span className="min-w-0 [overflow-wrap:anywhere]">
        <span className="text-text">{vorItemTitle(item)}</span>
        <span className="block text-muted">
          {vorItemQuantity(item)} (по ВОР){note ? ` · ${note}` : ''}
        </span>
      </span>
    </label>
  </li>
);

/**
 * Связь объекта Quantor (группа конструкций, тип двери, слой отделки МОП) со строками ВОР: тот же
 * механизм связей, что у конструкций. «Сохранить» заменяет прежние связи, «Отвязать всё» снимает.
 */
export const VorFillLinkDialog: FC<IDialogProps> = ({
  projectId,
  documentId,
  groupKey,
  title,
  linked,
  onClose,
}) => {
  const [selected, setSelected] = useState<ReadonlyMap<string, CadVorItemRead>>(
    () => new Map(linked.map((item) => [item.id, item])),
  );
  const [search, setSearch] = useState('');
  const [query, setQuery] = useState('');

  useEffect(() => {
    const timer = setTimeout(() => setQuery(search), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [search]);

  const suggest = useCadVorSuggest(projectId, groupKey, documentId, true);
  const items = useCadVorItems(
    projectId,
    documentId,
    { q: query, kind: null, thickness: null },
    true,
  );
  const put = usePutCadVorLinks(projectId);

  const toggle = (item: CadVorItemRead) =>
    setSelected((current) => {
      const next = new Map(current);
      if (next.has(item.id)) next.delete(item.id);
      else next.set(item.id, item);
      return next;
    });
  const save = (ids: readonly string[]) =>
    put.mutate({ groupKey, itemIds: ids }, { onSuccess: onClose });

  const suggestions = suggest.data ?? [];
  const rows = items.data?.items ?? [];

  return (
    <Dialog
      open
      onClose={onClose}
      size="lg"
      busy={put.isPending}
      title="Связать со строками ВОР"
      description={title}
      footer={
        <>
          <Button
            variant="danger"
            disabled={put.isPending || (linked.length === 0 && selected.size === 0)}
            onClick={() => {
              setSelected(new Map());
              save([]);
            }}
          >
            Отвязать всё
          </Button>
          <DialogActions>
            <Button onClick={onClose} disabled={put.isPending}>
              Отмена
            </Button>
            <Button
              variant="primary"
              disabled={put.isPending}
              onClick={() => save([...selected.keys()])}
            >
              Сохранить
            </Button>
          </DialogActions>
        </>
      }
    >
      {put.isError && (
        <p role="alert" className="text-xs text-danger">
          {vorErrorText(put.error)}
        </p>
      )}
      <section aria-label="Подсказки" className="flex flex-col gap-[var(--s-2)]">
        <h3 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">
          Подсказки
        </h3>
        {suggestions.length === 0 ? (
          <p className="text-xs text-muted">
            {suggest.isPending
              ? 'Подбор строк…'
              : 'Подходящих строк не нашлось: ищите по наименованию.'}
          </p>
        ) : (
          <ul className="m-0 list-none p-0">
            {suggestions.map(({ item, reasons }) => (
              <ItemRow
                key={item.id}
                item={item}
                checked={selected.has(item.id)}
                note={suggestReasonsText(reasons)}
                onToggle={toggle}
              />
            ))}
          </ul>
        )}
      </section>
      <section aria-label="Поиск по строкам ВОР" className="flex flex-col gap-[var(--s-3)]">
        <h3 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">
          Все строки ВОР
        </h3>
        <ClearableInput
          label="Поиск по наименованию"
          type="search"
          value={search}
          placeholder="Наименование"
          onChange={(event) => setSearch(event.target.value)}
          onClear={() => setSearch('')}
        />
        {items.isError ? (
          <p role="alert" className="text-xs text-danger">
            {vorErrorText(items.error)}
          </p>
        ) : rows.length === 0 ? (
          <p className="text-xs text-muted">
            {items.data === undefined ? 'Загрузка строк…' : 'Строк не найдено.'}
          </p>
        ) : (
          <>
            <ul className="m-0 list-none p-0">
              {rows.map((item) => (
                <ItemRow
                  key={item.id}
                  item={item}
                  checked={selected.has(item.id)}
                  onToggle={toggle}
                />
              ))}
            </ul>
            {(items.data?.total ?? 0) > VOR_ITEMS_LIMIT && (
              <p className="text-xs text-muted">
                Показано {rows.length} из {items.data?.total}: уточните поиск.
              </p>
            )}
          </>
        )}
      </section>
      <p className="text-xs text-muted">Выбрано строк: {selected.size}</p>
    </Dialog>
  );
};
