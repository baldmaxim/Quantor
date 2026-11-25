import type { VorObjectRead } from '@quantor/api-client';
import type { FC } from 'react';

import { Button } from '@/components/ui';
import { OBJECT_KIND_LABELS, objectQuantitiesText } from '@/lib/vor-fill/format';

/** Объекты Quantor: «нет в ВОР» (без связи) или все объекты проекта; «Связать» открывает выбор строк. */

interface IObjectsProps {
  readonly objects: readonly VorObjectRead[];
  readonly canLink: boolean;
  readonly emptyText: string;
  readonly onLink: (object: VorObjectRead) => void;
}

export const VorFillObjects: FC<IObjectsProps> = ({ objects, canLink, emptyText, onLink }) => {
  if (objects.length === 0) return <p className="text-xs text-muted">{emptyText}</p>;
  return (
    <ul className="m-0 flex list-none flex-col p-0">
      {objects.map((object) => (
        <li
          key={object.group_key}
          className="flex flex-wrap items-center gap-[var(--s-3)] border-t border-border py-[var(--s-2)] first:border-t-0"
        >
          <span className="min-w-0 flex-1 basis-[240px] text-xs [overflow-wrap:anywhere]">
            <span className="text-text">{object.title}</span>
            <span className="block text-muted">
              {OBJECT_KIND_LABELS[object.kind]} · {objectQuantitiesText(object)} · листов:{' '}
              {object.sources.length}
            </span>
          </span>
          {canLink && (
            <Button compact onClick={() => onLink(object)}>
              Связать с ВОР
            </Button>
          )}
        </li>
      ))}
    </ul>
  );
};
