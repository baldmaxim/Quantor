'use client';

import type { CadFloor3dWarningRead } from '@quantor/api-client';
import type { FC } from 'react';

interface ICadFloor3dWarningsProps {
  readonly warnings: readonly CadFloor3dWarningRead[];
}

/** Предупреждения модели этажа списком; предупреждений нет - ничего. */
export const CadFloor3dWarnings: FC<ICadFloor3dWarningsProps> = ({ warnings }) => {
  if (warnings.length === 0) return null;
  return (
    <section aria-label="Предупреждения" className="flex min-w-0 flex-col gap-[var(--s-3)]">
      <h4 className="text-micro font-semibold tracking-[0.06em] text-muted uppercase">Предупреждения</h4>
      <ul className="flex flex-col gap-[var(--s-2)]">
        {warnings.map((item) => (
          <li key={`${item.code}:${item.message}`} className="text-xs text-warning [overflow-wrap:anywhere]">
            {item.message}
          </li>
        ))}
      </ul>
    </section>
  );
};
