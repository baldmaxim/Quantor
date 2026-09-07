'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';

import { cx } from '@/components/ui';
import { ThemeToggle } from '@/components/ui/ThemeToggle';

/**
 * Шапка страничных маршрутов: путь слева, действия справа.
 *
 * Высота фиксирована токеном: шапка не должна прыгать при появлении бейджа или кнопки.
 * Шапка липкая — при прокрутке длинного списка путь и действия остаются на виду.
 *
 * На телефоне действия переносятся во вторую строку: пять контролов в ряд на 360 px
 * либо не помещаются, либо ужимаются до непопадаемых.
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
  <header
    // Имя перехода закрепляет шапку: контент едет, шапка стоит (см. globals.css).
    style={{ viewTransitionName: 'shell-topbar' }}
    className="safe-top sticky top-0 z-20 flex-none border-b border-border-strong bg-surface/95 backdrop-blur-sm"
  >
    <div className="flex min-h-[var(--h-topbar)] items-center gap-[var(--s-5)] px-[var(--s-5)] md:px-[var(--s-6)]">
      <nav
        aria-label="Хлебные крошки"
        className="flex min-w-0 flex-1 items-center gap-[var(--s-4)]"
      >
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
                  // Возврат: страница уезжает вправо, как назад по стопке.
                  transitionTypes={['nav-back']}
                  className="truncate text-sm text-muted transition-colors duration-[var(--dur-fast)] hover:text-text"
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

      <div className="flex flex-none items-center gap-[var(--s-4)]">
        {actions && <div className="hidden items-center gap-[var(--s-4)] md:flex">{actions}</div>}
        <ThemeToggle />
      </div>
    </div>

    {actions && (
      <div className="scroll-area flex items-center gap-[var(--s-4)] border-t border-border px-[var(--s-5)] py-[var(--s-4)] md:hidden">
        {actions}
      </div>
    )}
  </header>
);
