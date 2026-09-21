'use client';

import { ProgressRow, StatusBadge, type BadgeTone } from '@/components/ui';
import type { UploadItem, UploadStage } from '@/components/projects/UploadQueue';
import { formatBytes } from '@/lib/format';

/**
 * Ход загрузки файлов.
 *
 * Один на оба окна: в создании проекта список шёл во всю ширину без рамки, в
 * загрузке в проект — в рамке с отступами, а тон бейджа там считался тернарником,
 * терявшим состояния «ожидание» и «отменено».
 */

const STAGE_TONE: Record<UploadStage, BadgeTone> = {
  ожидание: 'neutral',
  загрузка: 'accent',
  готово: 'success',
  ошибка: 'danger',
  отменено: 'neutral',
};

export const UploadQueueList = ({ items }: { items: readonly UploadItem[] }) => {
  if (items.length === 0) return null;

  return (
    <ul className="flex flex-col gap-[var(--s-5)] rounded-[var(--radius-md)] border border-border px-[var(--s-6)] py-[var(--s-5)]">
      {items.map((item) => (
        <li key={item.id} className="flex flex-col gap-[var(--s-3)]">
          <div className="flex flex-wrap items-baseline gap-x-[var(--s-4)] gap-y-[var(--s-2)] text-xs">
            <span className="min-w-0 flex-1 truncate">{item.name}</span>
            <span className="mono text-muted">{formatBytes(item.size)}</span>
            <StatusBadge tone={STAGE_TONE[item.stage]} dot={false}>
              {/* Повтор — не ошибка: файл уже был загружен, и вторая копия не создаётся. */}
              {item.stage === 'готово' && item.duplicate ? 'уже был' : item.stage}
            </StatusBadge>
          </div>

          {item.stage === 'загрузка' && (
            <ProgressRow value={item.fraction} label={`Загрузка ${item.name}`} />
          )}

          {item.errorText && (
            <p className="text-xs text-danger">
              {item.errorText}
              {item.errorCode && <span className="mono text-muted"> · {item.errorCode}</span>}
            </p>
          )}
        </li>
      ))}
    </ul>
  );
};
