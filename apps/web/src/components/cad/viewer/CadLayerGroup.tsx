'use client';

import { useEffect, useRef, useState, type FC } from 'react';

import { cx } from '@/components/ui';
import { layerColorVar } from '@/lib/cad/layer-colors';
import type { ILayerGroup } from '@/lib/cad/layer-groups';

interface ICadLayerGroupProps {
  group: ILayerGroup;
  /** Имена всех слоёв DXF: индексы группы указывают сюда. */
  layers: readonly string[];
  visibleLayers: ReadonlySet<number>;
  onToggleLayer: (index: number) => void;
  /** Скрыть или показать все слои группы разом. */
  onSetLayersHidden: (indices: readonly number[], hidden: boolean) => void;
}

const CHECK = 'flex min-h-[44px] items-center gap-[var(--s-3)] text-sm';

/** Группа слоёв: сворачиваемый заголовок с общим чекбоксом видимости и слои группы. */
export const CadLayerGroup: FC<ICadLayerGroupProps> = ({
  group,
  layers,
  visibleLayers,
  onToggleLayer,
  onSetLayersHidden,
}) => {
  const [expanded, setExpanded] = useState(true);
  const master = useRef<HTMLInputElement>(null);

  const shown = group.indices.filter((index) => visibleLayers.has(index)).length;
  const all = shown === group.indices.length;
  const partial = shown > 0 && !all;

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
          onChange={() => onSetLayersHidden(group.indices, all)}
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
          return (
            <label key={`${index}-${name}`} className={CHECK}>
              <input
                type="checkbox"
                checked={on}
                onChange={() => onToggleLayer(index)}
                className="size-5 shrink-0"
              />
              <span
                aria-hidden="true"
                data-testid="layer-swatch"
                data-layer-on={on}
                // Цвет слоя - динамическое значение: токен палитры по порядку слоя.
                style={{ backgroundColor: layerColorVar(index) }}
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
            </label>
          );
        })}
      </div>
    </div>
  );
};
