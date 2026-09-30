'use client';

import Link from 'next/link';

import { usePendingUsersCount } from '@/lib/queries';

/**
 * Заявки в шапке: видны на любой ширине экрана.
 *
 * Отметка в навигации на узком экране спрятана вместе с самой навигацией — за кнопкой
 * «Разделы». Шапка видна всегда, и ждущая заявка не должна зависеть от того, раскрыто ли меню.
 */
export const PendingRequestsLink = () => {
  const { data } = usePendingUsersCount();
  if (!data) return null;

  return (
    <Link
      href="/users"
      className="press inline-flex h-[32px] flex-none items-center rounded-full bg-warning-soft px-[var(--s-4)] text-xs font-semibold text-warning max-lg:h-[44px]"
    >
      Заявки: {data}
    </Link>
  );
};
