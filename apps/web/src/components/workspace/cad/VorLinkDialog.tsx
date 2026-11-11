'use client';

import type { CadVorCoverageGroupRead, CadVorItemRead } from '@quantor/api-client';
import { useEffect, useState, type FC } from 'react';

import { Button, Dialog, DialogActions } from '@/components/ui';
import { ClearableInput } from '@/components/ui/ClearableInput';
import {
  suggestReasonsText,
  vorGroupLabel,
  vorItemQuantity,
  vorItemTitle,
} from '@/lib/cad/vor';
import {
  useCadVorItems,
  useCadVorSuggest,
  usePutCadVorLinks,
  vorErrorText,
  VOR_ITEMS_LIMIT,
} from '@/lib/cad/vor-queries';

interface IVorLinkDialogProps {
  projectId: string;
  documentId: string;
  group: CadVorCoverageGroupRead;
  onClose: () => void;
}

const SEARCH_DELAY_MS = 300;

interface IItemRowProps {
  item: CadVorItemRead;
  checked: boolean;
  note?: string;
  onToggle: (item: CadVorItemRead) => void;
}

const ItemRow: FC<IItemRowProps> = ({ item, checked, note, onToggle }) => (
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
          {vorItemQuantity(item)} (по ВОР, на весь объект)
          {note ? ` · ${note}` : ''}
        </span>
      </span>
    </label>
  </li>
);

const parseThickness = (raw: string): number | null => {
  const value = Number(raw.trim().replace(',', '.'));
  return raw.trim() !== '' && Number.isFinite(value) && value > 0 ? Math.round(value) : null;
};

/**
 * Сопоставление группы конструкций со строками ВОР: сверху подсказки сервера с причинами, ниже поиск
 * по строкам. Выбор - полный набор строк группы: «Сохранить» заменяет прежние связи, «Отвязать всё»
 * снимает их. Связь ставит человек; количества ВОР только показаны.
 */
export const VorLinkDialog: FC<IVorLinkDialogProps> = ({ projectId, documentId, group, onClose }) => {
  const [selected, setSelected] = useState<ReadonlyMap<string, CadVorItemRead>>(
    () => new Map(group.items.map((item) => [item.id, item])),
  );
  const [search, setSearch] = useState('');
  const [thickness, setThickness] = useState('');
  const [query, setQuery] = useState('');

  useEffect(() => {
    const timer = setTimeout(() => setQuery(search), SEARCH_DELAY_MS);
    return () => clearTimeout(timer);
  }, [search]);

  const suggest = useCadVorSuggest(projectId, group.group_key, documentId, true);
  const items = useCadVorItems(
    projectId,
    documentId,
    { q: query, kind: null, thickness: parseThickness(thickness) },
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
    put.mutate({ groupKey: group.group_key, itemIds: ids }, { onSuccess: onClose });

  const suggestions = suggest.data ?? [];
  const rows = items.data?.items ?? [];

  return (
    <Dialog
      open
      onClose={onClose}
      size="lg"
      busy={put.isPending}
      title="Сопоставить с ВОР"
      description={vorGroupLabel(group)}
      footer={
        <>
          <Button
            variant="danger"
            disabled={put.isPending || (group.items.length === 0 && selected.size === 0)}
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
        <h3 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">Подсказки</h3>
        {suggest.isPending ? (
          <p role="status" className="text-xs text-muted">
            Подбор строк…
          </p>
        ) : suggestions.length === 0 ? (
          <p className="text-xs text-muted">Подходящих строк не нашлось: ищите по наименованию.</p>
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
        <h3 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">Все строки ВОР</h3>
        <div className="flex flex-wrap gap-[var(--s-3)]">
          <ClearableInput
            label="Поиск по наименованию"
            type="search"
            value={search}
            placeholder="Наименование"
            wrapperClassName="min-w-0 flex-1 basis-[200px]"
            onChange={(event) => setSearch(event.target.value)}
            onClear={() => setSearch('')}
          />
          <ClearableInput
            label="Толщина, мм"
            inputMode="numeric"
            value={thickness}
            maxLength={4}
            placeholder="Толщина, мм"
            wrapperClassName="w-[140px]"
            onChange={(event) => setThickness(event.target.value)}
            onClear={() => setThickness('')}
          />
        </div>
        {items.isError ? (
          <p role="alert" className="text-xs text-danger">
            {vorErrorText(items.error)}
          </p>
        ) : items.data === undefined ? (
          <p role="status" className="text-xs text-muted">
            Загрузка строк…
          </p>
        ) : rows.length === 0 ? (
          <p className="text-xs text-muted">Строк не найдено.</p>
        ) : (
          <>
            <ul className="m-0 list-none p-0">
              {rows.map((item) => (
                <ItemRow key={item.id} item={item} checked={selected.has(item.id)} onToggle={toggle} />
              ))}
            </ul>
            {items.data.total > VOR_ITEMS_LIMIT && (
              <p className="text-xs text-muted">
                Показано {rows.length} из {items.data.total}: уточните поиск.
              </p>
            )}
          </>
        )}
      </section>

      <p className="text-xs text-muted">Выбрано строк: {selected.size}</p>
    </Dialog>
  );
};
