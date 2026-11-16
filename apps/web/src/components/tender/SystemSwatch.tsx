import type { FC } from 'react';

import { systemColorToken } from '@/lib/tender/systems';

/** Цветная точка системы: цвет задаёт токен темы, поэтому значение — динамическое. */
export const SystemSwatch: FC<{ readonly system: string }> = ({ system }) => (
  <span
    aria-hidden="true"
    className="inline-block h-[10px] w-[10px] shrink-0 rounded-full"
    style={{ backgroundColor: `var(${systemColorToken(system)})` }}
  />
);
