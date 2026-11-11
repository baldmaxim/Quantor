'use client';

import { useEffect, useRef, type FC, type ReactNode } from 'react';

export type ZoneGroupSelection = 'none' | 'some' | 'all';

interface ICadZoneSpecGroupProps {
  title: string;
  summary?: string;
  expanded: boolean;
  onToggle: () => void;
  /** Флажок выбора всех помещений группы; `null` - без флажка. */
  selection?: { state: ZoneGroupSelection; label: string; onToggle: () => void } | null;
  children: ReactNode;
}

/** Сворачиваемая группа спецификации зон: заголовок-кнопка с итогом и содержимое. */
export const CadZoneSpecGroup: FC<ICadZoneSpecGroupProps> = ({
  title,
  summary = '',
  expanded,
  onToggle,
  selection = null,
  children,
}) => {
  const boxRef = useRef<HTMLInputElement>(null);
  const selectionState = selection?.state;
  useEffect(() => {
    if (boxRef.current) boxRef.current.indeterminate = selectionState === 'some';
  }, [selectionState]);

  return (
    <section className="flex min-w-0 flex-col">
      <div className="flex min-w-0 items-stretch border-b border-border">
        {selection !== null && (
          <label className="grid h-[44px] w-[44px] shrink-0 cursor-pointer place-items-center">
            <input
              ref={boxRef}
              type="checkbox"
              aria-label={selection.label}
              checked={selection.state === 'all'}
              onChange={selection.onToggle}
              className="h-[18px] w-[18px] accent-[var(--accent)]"
            />
          </label>
        )}
        <h4 className="m-0 flex min-w-0 flex-1 text-xs font-semibold">
          <button
            type="button"
            aria-expanded={expanded}
            onClick={onToggle}
            className="flex min-h-[44px] w-full min-w-0 items-center gap-[var(--s-2)] text-left md:min-h-[32px]"
          >
            <span aria-hidden="true" className="w-[1em] shrink-0 text-muted">
              {expanded ? '▾' : '▸'}
            </span>
            <span className="min-w-0 flex-1 break-words">{title}</span>
            {summary !== '' && <span className="shrink-0 font-normal text-muted">{summary}</span>}
          </button>
        </h4>
      </div>
      {expanded && <div className="flex min-w-0 flex-col">{children}</div>}
    </section>
  );
};
