'use client';

import { useState, type FC } from 'react';

import { Button, EmptyState, cx } from '@/components/ui';
import type { TakeoffItemQuantityRead, TakeoffItemRead } from '@quantor/api-client';

/** Типы, которые пользователь выбирает при создании строки. */
const GEOMETRY_CHOICES = [
  { value: 'count', label: 'Количество', unit: 'шт' },
  { value: 'line', label: 'Линия', unit: 'м' },
  { value: 'polyline', label: 'Ломаная', unit: 'м' },
  { value: 'polygon', label: 'Площадь', unit: 'м²' },
] as const;

export type TakeoffGeometry = (typeof GEOMETRY_CHOICES)[number]['value'];

/** Как показывается единица строки. Отдельно от API: там она хранится как `pcs`/`m`/`m2`. */
export const UNIT_LABELS: Record<string, string> = { pcs: 'шт', m: 'м', m2: 'м²' };

/**
 * Итог по строке на открытом листе.
 *
 * Раньше здесь показывалось число измерений с единицей строки — «3 м» означало три линии,
 * а читалось как три метра. Теперь показывается величина, а число измерений ушло в
 * подпись: это разные величины, и путать их в смете нельзя.
 *
 * Недоступные измерения считаются отдельно, а не нулями: итог, в котором половина строк
 * «стоила ноль», невозможно ни заметить, ни объяснить.
 */
const ItemTotal: FC<{
  total: TakeoffItemQuantityRead | null;
  measurements: number;
  unit: string;
}> = ({ total, measurements, unit }) => {
  if (measurements === 0) return <span className="tabular text-micro text-muted">—</span>;
  if (!total) return <span className="tabular text-micro text-muted">…</span>;

  const value = Number(total.value).toLocaleString('ru-RU', { maximumFractionDigits: 2 });

  return (
    <span className="tabular text-micro text-muted" title={`Измерений: ${measurements}`}>
      {total.measurement_count === 0 ? '—' : `${value} ${unit}`}
      {total.unavailable_count > 0 && (
        <span className="text-danger"> +{total.unavailable_count} без масштаба</span>
      )}
    </span>
  );
};

interface ITakeoffPanelProps {
  readonly items: readonly TakeoffItemRead[];
  readonly activeItemId: string | null;
  readonly counts: Readonly<Record<string, number>>;
  /** Итоги по строкам на открытом листе. Считает сервер. */
  readonly totals: Readonly<Record<string, TakeoffItemQuantityRead>>;
  readonly canEdit: boolean;
  readonly pending: boolean;
  readonly onSelect: (itemId: string) => void;
  readonly onCreate: (name: string, geometryType: TakeoffGeometry) => void;
  readonly onArchive: (itemId: string) => void;
}

/**
 * Список строк обмера.
 *
 * Строки заводит пользователь и называет их сам: строительные категории портал не
 * придумывает. «Двери», «Перегородка ПГ-1», «Пол в осях 1–5» — это его язык, а не наш
 * классификатор (ADR-0019).
 */
export const TakeoffPanel: FC<ITakeoffPanelProps> = ({
  items,
  activeItemId,
  counts,
  totals,
  canEdit,
  pending,
  onSelect,
  onCreate,
  onArchive,
}) => {
  const [creating, setCreating] = useState(false);
  const [name, setName] = useState('');
  const [geometry, setGeometry] = useState<TakeoffGeometry>('count');

  const submit = () => {
    const cleaned = name.trim();
    if (!cleaned || pending) return;
    onCreate(cleaned, geometry);
    setName('');
    setCreating(false);
  };

  return (
    <div className="flex h-full flex-col">
      <div className="scroll-area flex-1">
        {items.length === 0 && !creating ? (
          <EmptyState
            title="Строк обмера нет"
            description="Заведите строку и выберите, что она считает: количество, длину или площадь."
          />
        ) : (
          <ul className="flex flex-col">
            {items.map((item) => {
              const active = item.id === activeItemId;
              return (
                <li key={item.id}>
                  <button
                    type="button"
                    onClick={() => onSelect(item.id)}
                    aria-pressed={active}
                    className={cx(
                      'flex h-[var(--h-row-tree)] w-full items-center gap-[var(--s-3)]',
                      'px-[var(--s-4)] text-left text-body',
                      active ? 'bg-accent-soft text-accent' : 'hover:bg-surface-muted',
                    )}
                  >
                    <span
                      aria-hidden
                      className="size-[10px] shrink-0 rounded-[2px] bg-accent"
                      data-color-key={item.color_key}
                    />
                    <span className="min-w-0 flex-1 truncate">{item.name}</span>
                    <ItemTotal
                      total={totals[item.id] ?? null}
                      measurements={counts[item.id] ?? 0}
                      unit={UNIT_LABELS[item.display_unit] ?? ''}
                    />
                    {canEdit && (
                      <span
                        role="button"
                        tabIndex={0}
                        aria-label={`Архивировать «${item.name}»`}
                        onClick={(event) => {
                          event.stopPropagation();
                          onArchive(item.id);
                        }}
                        onKeyDown={(event) => {
                          if (event.key !== 'Enter' && event.key !== ' ') return;
                          event.stopPropagation();
                          onArchive(item.id);
                        }}
                        className="text-micro text-muted hover:text-danger"
                      >
                        в архив
                      </span>
                    )}
                  </button>
                </li>
              );
            })}
          </ul>
        )}
      </div>

      {canEdit && (
        <div className="border-t border-line p-[var(--s-4)]">
          {creating ? (
            <div className="flex flex-col gap-[var(--s-3)]">
              <input
                autoFocus
                value={name}
                onChange={(event) => setName(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === 'Enter') submit();
                  if (event.key === 'Escape') setCreating(false);
                }}
                aria-label="Название строки"
                placeholder="Например, Двери"
                className="h-[var(--h-ctl)] rounded-[var(--radius-sm)] border border-line bg-canvas px-[var(--s-3)] text-body"
              />
              <div className="grid grid-cols-2 gap-[var(--s-2)]">
                {GEOMETRY_CHOICES.map((choice) => (
                  <button
                    key={choice.value}
                    type="button"
                    onClick={() => setGeometry(choice.value)}
                    aria-pressed={geometry === choice.value}
                    className={cx(
                      'h-[var(--h-ctl-ws)] rounded-[var(--radius-sm)] border text-micro',
                      geometry === choice.value
                        ? 'border-accent bg-accent-soft text-accent'
                        : 'border-line text-muted',
                    )}
                  >
                    {choice.label}
                    {/* Единица не выбирается: она следует из типа (ADR-0019). */}
                    <span className="ml-[var(--s-2)] text-muted">{choice.unit}</span>
                  </button>
                ))}
              </div>
              <div className="flex justify-end gap-[var(--s-2)]">
                <Button variant="ghost" compact onClick={() => setCreating(false)}>
                  Отмена
                </Button>
                <Button variant="primary" compact onClick={submit} disabled={!name.trim()}>
                  Создать
                </Button>
              </div>
            </div>
          ) : (
            <Button compact onClick={() => setCreating(true)}>
              Новая строка
            </Button>
          )}
        </div>
      )}
    </div>
  );
};
