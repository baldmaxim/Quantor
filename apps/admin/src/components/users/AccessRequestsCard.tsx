'use client';

import { Button, buttonClassName, cx } from '@quantor/ui';
import Link from 'next/link';
import { useId, useState } from 'react';

import { env } from '@/lib/env';
import { usePendingUsersCount } from '@/lib/queries';
import { pendingSummary, registrationUrl } from '@/lib/users';

/**
 * Как люди получают доступ к порталу — и сколько заявок ждёт прямо сейчас.
 *
 * Заявку подают без администратора, а почты портал не рассылает: не зная этого пути,
 * администратор не найдёт, где выдавать доступ. Поэтому путь расписан по шагам, а ссылка
 * на форму заявки дана готовой — её отправляют коллегам.
 */

interface IAccessRequestsCardProps {
  /** Переход в раздел заявок — на обзоре. В самом разделе он не нужен. */
  withLink?: boolean;
}

export const AccessRequestsCard = ({ withLink = false }: IAccessRequestsCardProps) => {
  const pending = usePendingUsersCount();
  const [copied, setCopied] = useState(false);
  const titleId = useId();

  const count = pending.data ?? 0;
  const link = registrationUrl(env.portalUrl);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
    } catch {
      // Буфер обмена недоступен (нет разрешения) — ссылка остаётся на экране.
      setCopied(false);
    }
  };

  return (
    <section
      aria-labelledby={titleId}
      className={cx(
        'flex flex-col gap-[var(--s-4)] rounded-[var(--radius-md)] border px-[var(--s-6)] py-[var(--s-5)]',
        count > 0 ? 'border-warning-soft bg-warning-soft' : 'border-border bg-surface',
      )}
    >
      <div className="flex flex-wrap items-center justify-between gap-[var(--s-4)]">
        <div className="flex flex-col gap-[2px]">
          <h2 id={titleId} className="text-md font-medium">
            Заявки на доступ
          </h2>
          {pending.isSuccess && (
            <span className={cx('text-sm', count > 0 ? 'text-warning' : 'text-muted')}>
              {pendingSummary(count)}
            </span>
          )}
        </div>
        {withLink && (
          // Вид кнопки не зависит от числа: иначе она перекрашивалась бы, когда число догрузится.
          <Link href="/users" className={buttonClassName({ variant: 'primary' })}>
            {count > 0 ? 'Рассмотреть заявки' : 'Пользователи и доступ'}
          </Link>
        )}
      </div>

      <ol className="flex list-decimal flex-col gap-[var(--s-2)] pl-[var(--s-6)] text-sm">
        <li>
          Коллега открывает портал и нажимает «Подать заявку» — или сразу переходит по ссылке ниже.
        </li>
        <li>Заявка появляется в разделе «Пользователи и доступ», на вкладке «Заявки».</li>
        <li>
          Нажмите «Одобрить» в строке заявки и выберите рабочее пространство и роль — доступ
          откроется сразу.
        </li>
      </ol>

      <div className="flex flex-wrap items-center gap-[var(--s-3)]">
        <span className="text-xs text-muted">Ссылка для коллег:</span>
        <span className="mono text-xs wrap-anywhere">{link}</span>
        <Button compact onClick={() => void copy()}>
          {copied ? 'Скопирована' : 'Скопировать'}
        </Button>
      </div>
    </section>
  );
};
