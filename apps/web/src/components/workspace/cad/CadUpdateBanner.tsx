import { cx } from '@quantor/ui';
import type { FC } from 'react';

import { formatWhen } from '@/lib/format';

import type { IWorkspaceCadUpdate } from './types';

/**
 * Плашка над панелью CAD: новый прогон листа идёт или упал, а на экране прежний готовый CAD.
 * Прежний результат не прячется: плашка только сообщает о состоянии обновления.
 */
export const CadUpdateBanner: FC<{ update: IWorkspaceCadUpdate }> = ({ update }) => {
  const failed = update.status === 'failed' || update.status === 'cancelled';
  const reason =
    update.errorText ?? (update.status === 'cancelled' ? 'задание отменено' : 'причина не указана');
  const shownAt = update.shownAt !== null ? formatWhen(update.shownAt) : null;
  return (
    <div
      role={failed ? 'alert' : 'status'}
      data-testid="workspace-cad-update"
      className={cx(
        'flex-none px-[var(--s-5)] py-[var(--s-3)] text-xs [overflow-wrap:anywhere]',
        failed ? 'bg-danger-soft text-danger' : 'bg-info-soft text-info',
      )}
    >
      {failed
        ? `Обновление CAD не удалось: ${reason}. Показан прежний прогон.`
        : `Идёт обновление CAD листа. Показан прежний прогон${shownAt !== null ? ` от ${shownAt}` : ''}.`}
    </div>
  );
};
