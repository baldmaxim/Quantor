'use client';

import { useEffect, useRef, useState, type FC } from 'react';

import { cx } from '@/components/ui';
import { layerColorVar } from '@/lib/cad/layer-colors';
import type { ILayerGroup } from '@/lib/cad/layer-groups';
import { formatInt } from '@/lib/cad/view-format';

interface ICadLayerGroupProps {
  group: ILayerGroup;
  /** Имена всех слоёв DXF: индексы группы указывают сюда. */
  layers: readonly string[];
  visibleLayers: ReadonlySet<number>;
  onToggleLayer: (index: number) => void;
  /** Скрыть или показать все слои группы разом. */
  onSetLayersHidden: (indices: readonly number[], hidden: boolean) => void;
  /** Цвет образца слоя; по умолчанию - токен палитры по порядку слоя. */
  swatchColor?: (index: number) => string;
  /** Слои, которые сейчас недоступны (в 3D - без категории конструкций): неактивны, с пометкой. */
  disabledIndices?: ReadonlySet<number>;
  /** Пометка у недоступного слоя. */
  disabledNote?: string;
  /** Число справа у пункта; `null` или нет функции - без числа. */
  countOf?: (index: number) => number | null;
  /** Число у заголовка группы; `null` или нет - без числа. */
  groupCount?: number | null;
}

const CHECK = 'flex min-h-[44px] items-center gap-[var(--s-3)] text-sm';

/** Группа слоёв: сворачиваемый заголовок с общим чекбоксом видимости и слои группы. */
export const CadLayerGroup: FC<ICadLayerGroupProps> = ({
  group,
  layers,
  visibleLayers,
  onToggleLayer,
  onSetLayersHidden,
  swatchColor = layerColorVar,
  disabledIndices,
  disabledNote = '',
  countOf,
  groupCount = null,
}) => {
  const [expanded, setExpanded] = useState(true);
  const master = useRef<HTMLInputElement>(null);

  // Переключатель группы действует только на доступные слои.
  const enabled = group.indices.filter((index) => !disabledIndices?.has(index));
  const shown = group.indices.filter((index) => visibleLayers.has(index)).length;
  const shownEnabled = enabled.filter((index) => visibleLayers.has(index)).length;
  const all = enabled.length > 0 && shownEnabled === enabled.length;
  const partial = shownEnabled > 0 && !all;

  // Неопределённое состояние выставляется только через DOM-свойство.
  useEffect(() => {
    if (master.current) master.current.indeterminate = partial;
  }, [partial]);

  const bodyId = `layer-group-${group.key}`;

  return (
    <div className="flex min-w-0 flex-col" data-testid={`layer-group-${group.key}`}>
      <div className="flex min-h-[44px] items-center gap-[var(--s-3)]">
        <input
          ref={master}
          type="checkbox"
          checked={all}
          onChange={() => onSetLayersHidden(enabled, all)}
          disabled={enabled.length === 0}
          aria-label={`Группа «${group.label}»`}
          className="size-5 shrink-0"
        />
        <button
          type="button"
          aria-expanded={expanded}
          aria-controls={bodyId}
          onClick={() => setExpanded((value) => !value)}
          className="flex min-h-[44px] min-w-0 flex-1 items-center gap-[var(--s-3)] text-left text-sm font-medium"
        >
          <span className="min-w-0 [overflow-wrap:anywhere]">{group.label}</span>
          <span className="tabular text-xs font-normal text-muted">
            {shown} / {group.indices.length}
          </span>
          {groupCount !== null && (
            <span className="tabular text-xs font-normal text-muted" data-testid="layer-group-count">
              {formatInt(groupCount)}
            </span>
          )}
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            className={cx(
              'ml-auto h-[16px] w-[16px] shrink-0 text-muted transition-transform',
              !expanded && '-rotate-90',
            )}
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
            strokeLinejoin="round"
          >
            <path d="M6 9l6 6 6-6" />
          </svg>
        </button>
      </div>

      <div id={bodyId} hidden={!expanded} className="flex flex-col pl-[var(--s-6)]">
        {group.indices.map((index) => {
          const name = layers[index] ?? '';
          const on = visibleLayers.has(index);
          const unavailable = disabledIndices?.has(index) === true;
          const count = countOf?.(index) ?? null;
          return (
            <label
              key={`${index}-${name}`}
              className={cx(CHECK, unavailable && 'opacity-60')}
              data-unavailable={unavailable || undefined}
            >
              <input
                type="checkbox"
                checked={on}
                disabled={unavailable}
                onChange={() => onToggleLayer(index)}
                className="size-5 shrink-0"
              />
              <span
                aria-hidden="true"
                data-testid="layer-swatch"
                data-layer-on={on}
                // Цвет слоя - динамическое значение: токен темы.
                style={{ backgroundColor: swatchColor(index) }}
                className={cx(
                  'size-4 shrink-0 rounded-[var(--radius-xs)] border border-border-strong transition-opacity',
                  !on && 'opacity-30',
                )}
              />
              <span
                className={cx(
                  'mono text-xs [overflow-wrap:anywhere]',
                  !on && 'text-muted line-through',
                )}
              >
                {name}
              </span>
              {unavailable && disabledNote !== '' && (
                <span className="ml-auto text-xs text-muted">{disabledNote}</span>
              )}
              {count !== null && (
                <span className="tabular ml-auto text-xs text-muted" data-testid="layer-count">
                  {formatInt(count)}
                </span>
              )}
            </label>
          );
        })}
      </div>
    </div>
  );
};
