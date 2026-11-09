'use client';

import { useState, type FC } from 'react';

import { Button, cx } from '@/components/ui';
import {
  REMARK_STATUS_LABELS,
  remarkTypeLabel,
  type IRemark,
  type RemarkStatus,
} from '@/lib/cad/remarks';

interface ICadRemarkItemProps {
  number: number;
  remark: IRemark;
  active: boolean;
  onActivate: () => void;
  onStatusChange: (status: RemarkStatus) => void;
  /** Подвести камеру к участку; `null` - недоступно. */
  onFocus: (() => void) | null;
  onDelete: () => void;
}

/** Строка списка замечаний: номер, тип, комментарий, статус, «К участку», удаление с подтверждением. */
export const CadRemarkItem: FC<ICadRemarkItemProps> = ({
  number,
  remark,
  active,
  onActivate,
  onStatusChange,
  onFocus,
  onDelete,
}) => {
  const [confirming, setConfirming] = useState(false);
  const resolved = remark.status === 'resolved';

  return (
    <li
      data-testid="remark-item"
      data-status={remark.status}
      aria-current={active ? 'true' : undefined}
      className={cx(
        'flex min-w-0 flex-col gap-[var(--s-3)] border-b border-border px-[var(--s-5)] py-[var(--s-4)] last:border-b-0',
        active && 'bg-accent-soft',
      )}
    >
      <div className="flex min-w-0 items-start gap-[var(--s-4)]">
        {/* Номер повторяет плашку на листе: открытое - сплошная, проверенное - пунктир и галочка. */}
        <span
          aria-hidden="true"
          className={cx(
            'tabular grid h-[24px] min-w-[28px] shrink-0 place-items-center rounded-[var(--radius-xs)] px-[var(--s-2)] text-xs font-semibold',
            resolved
              ? 'border-2 border-dashed border-[var(--region-image)] text-[var(--region-image)]'
              : 'bg-[var(--sheet-ink-danger)] text-[var(--region-tag-text)]',
          )}
        >
          {resolved ? `${number} ✓` : number}
        </span>
        <button
          type="button"
          onClick={onActivate}
          className="min-h-[44px] min-w-0 flex-1 text-left [overflow-wrap:anywhere]"
          aria-label={`Замечание ${number}: ${remarkTypeLabel(remark.type)}`}
        >
          <span className="block text-sm font-medium">{remarkTypeLabel(remark.type)}</span>
          {remark.comment && (
            <span className="block text-xs whitespace-pre-wrap text-muted">{remark.comment}</span>
          )}
        </button>
      </div>

      <div className="flex flex-wrap items-center gap-[var(--s-3)]">
        <label className="flex min-h-[44px] cursor-pointer items-center gap-[var(--s-3)] text-xs">
          <input
            type="checkbox"
            checked={resolved}
            onChange={(event) => onStatusChange(event.target.checked ? 'resolved' : 'open')}
            className="size-5 shrink-0"
          />
          {REMARK_STATUS_LABELS[remark.status]}
        </label>
        {onFocus && (
          <Button compact onClick={onFocus} className="max-md:h-[44px]">
            К участку
          </Button>
        )}
        {confirming ? (
          <span
            className="flex items-center gap-[var(--s-3)]"
            role="group"
            aria-label="Подтверждение удаления"
          >
            <span className="text-xs">Удалить?</span>
            <Button compact variant="danger" onClick={onDelete} className="max-md:h-[44px]">
              Да, удалить
            </Button>
            <Button compact onClick={() => setConfirming(false)} className="max-md:h-[44px]">
              Нет
            </Button>
          </span>
        ) : (
          <Button
            compact
            variant="danger"
            onClick={() => setConfirming(true)}
            aria-label={`Удалить замечание ${number}`}
            className="max-md:h-[44px]"
          >
            Удалить
          </Button>
        )}
      </div>
    </li>
  );
};
