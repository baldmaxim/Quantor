'use client';

import type { CadHintResultRead } from '@quantor/api-client';
import type { FC } from 'react';

import { REMARK_TYPES } from '@/lib/cad/remarks';

interface IConstructionsHintsResultProps {
  hints: readonly CadHintResultRead[];
}

const HEADING = 'text-micro font-semibold tracking-[0.06em] text-muted uppercase';

const typeLabel = (type: string): string =>
  REMARK_TYPES.find((item) => item.value === type)?.label ?? type;

const statusText = (hint: CadHintResultRead): string => {
  if (hint.status === 'applied') return 'применена';
  if (hint.status === 'no_candidate') {
    return hint.reason ? `кандидата нет: ${hint.reason}` : 'кандидата нет';
  }
  return hint.reason ? `не поддерживается: ${hint.reason}` : 'не поддерживается';
};

/** Итог подсказок последнего перестроения по замечаниям: тип, статус, добавлено и снято. */
export const ConstructionsHintsResult: FC<IConstructionsHintsResultProps> = ({ hints }) => (
  <section
    data-testid="constructions-hints-result"
    aria-label="Итог подсказок"
    className="flex min-w-0 flex-col gap-[var(--s-2)]"
  >
    <h3 className={HEADING}>Итог подсказок</h3>
    <ul className="flex min-w-0 flex-col">
      {hints.map((hint) => (
        <li
          key={hint.id}
          data-testid="hint-result"
          data-status={hint.status}
          className="flex min-w-0 flex-col gap-[var(--s-1)] border-t border-border py-[var(--s-3)] text-xs first:border-t-0"
        >
          <span className="text-text">{typeLabel(hint.type)}</span>
          <span
            className={
              hint.status === 'applied' ? 'text-text' : 'text-muted [overflow-wrap:anywhere]'
            }
          >
            {statusText(hint)}
          </span>
          <span className="text-muted">
            добавлено: {hint.added_ids?.length ?? 0}, снято: {hint.removed_ids?.length ?? 0}
          </span>
        </li>
      ))}
    </ul>
  </section>
);
