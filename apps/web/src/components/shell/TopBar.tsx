'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';

import { cx } from '@/components/ui';

/**
 * Шапка страничных маршрутов: путь слева, действия справа.
 *
 * Высота фиксирована токеном: шапка не должна прыгать при появлении бейджа или кнопки.
 */

export interface Crumb {
  readonly label: string;
  readonly href?: string;
}

interface ITopBarProps {
  crumbs: readonly Crumb[];
  actions?: ReactNode;
  status?: ReactNode;
}

export const TopBar = ({ crumbs, actions, status }: ITopBarProps) => (
  <header className="flex h-[var(--h-topbar)] flex-none items-center gap-[var(--s-6)] border-b border-border-strong bg-surface px-[var(--s-6)]">
    <nav aria-label="Хлебные крошки" className="flex min-w-0 items-center gap-[var(--s-4)]">
      {crumbs.map((crumb, index) => {
        const last = index === crumbs.length - 1;
        return (
          <span key={crumb.label} className="flex min-w-0 items-center gap-[var(--s-4)]">
            {index > 0 && (
              <span aria-hidden="true" className="text-muted opacity-60">
                /
              </span>
            )}
            {crumb.href && !last ? (
              <Link
                href={crumb.href}
                className="truncate text-sm text-muted transition-colors hover:text-text"
              >
                {crumb.label}
              </Link>
            ) : (
              <span
                className={cx('truncate text-sm', last ? 'font-medium text-text' : 'text-muted')}
                aria-current={last ? 'page' : undefined}
              >
                {crumb.label}
              </span>
            )}
          </span>
        );
      })}
      {status}
    </nav>

    {actions && <div className="ml-auto flex items-center gap-[var(--s-4)]">{actions}</div>}
  </header>
);
