'use client';

import type { SheetPassportStatus } from '@quantor/api-client';
import type { FC } from 'react';

import { Button } from '@/components/ui';

/** Панель выбранных строк: подтвердить, отклонить, снять выбор. */

interface IBulkBarProps {
  readonly count: number;
  readonly pending: boolean;
  readonly error: string | null;
  readonly onStatus: (status: SheetPassportStatus) => void;
  readonly onClear: () => void;
}

export const SheetPassportBulkBar: FC<IBulkBarProps> = ({
  count,
  pending,
  error,
  onStatus,
  onClear,
}) => (
  <div
    role="region"
    aria-label="Выбранные листы"
    className="flex flex-wrap items-center gap-[var(--s-4)] rounded-[var(--radius-md)] border border-accent-soft bg-accent-soft px-[var(--s-5)] py-[var(--s-3)]"
  >
    <span className="tabular text-sm font-medium">Выбрано: {count}</span>
    <Button variant="primary" loading={pending} onClick={() => onStatus('confirmed')}>
      Подтвердить выбранные
    </Button>
    <Button variant="danger" disabled={pending} onClick={() => onStatus('rejected')}>
      Отклонить выбранные
    </Button>
    <Button variant="ghost" disabled={pending} onClick={onClear}>
      Снять выбор
    </Button>
    {error && (
      <p role="alert" className="w-full text-sm text-danger">
        {error}
      </p>
    )}
  </div>
);
