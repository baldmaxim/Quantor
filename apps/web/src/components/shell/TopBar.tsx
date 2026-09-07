'use client';

import Link from 'next/link';
import type { ReactNode } from 'react';

import { ThemeToggle } from '@/components/ui/ThemeToggle';

/**
 * Шапка страничных маршрутов: путь слева, действия справа.
 *
 * Высота фиксирована токеном: шапка не должна прыгать при появлении бейджа или кнопки.
 * Шапка липкая — при прокрутке длинного списка путь и действия остаются на виду.
 *
 * На телефоне действия переносятся во вторую строку: пять контролов в ряд на 360 px
 * либо не помещаются, либо ужимаются до непопадаемых.
 *
 * Последняя крошка — это и есть заголовок страницы, поэтому она размечена как `h1`.
 * Дублировать её ещё раз в теле страницы незачем: одно и то же слово дважды подряд
 * не помогает сориентироваться, а только съедает высоту экрана.
 */

export interface Crumb {
  readonly label: string;
  readonly href?: string;
}

interface ITopBarProps {
  crumbs: readonly Crumb[];
  actions?: ReactNode;
  status?: ReactNode;
  /** Короткая сводка под стать разделу: сколько проектов, документов. */
  summary?: ReactNode;
}

export const TopBar = ({ crumbs, actions, status, summary }: ITopBarProps) => (
  <header
    // Имя перехода закрепляет шапку: контент едет, шапка стоит (см. globals.css).
    style={{ viewTransitionName: 'shell-topbar' }}
    className="safe-top sticky top-0 z-20 flex-none border-b border-border-strong bg-surface/95 backdrop-blur-sm"
  >
    <div className="flex min-h-[var(--h-topbar)] items-center gap-[var(--s-5)] px-[var(--s-5)] md:px-[var(--s-6)]">
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
                  // Возврат: страница уезжает вправо, как назад по стопке.
                  transitionTypes={['nav-back']}
                  className="truncate text-sm text-muted transition-colors duration-[var(--dur-fast)] hover:text-text"
                >
                  {crumb.label}
                </Link>
              ) : last ? (
                <h1 className="truncate text-sm font-medium text-text" aria-current="page">
                  {crumb.label}
                </h1>
              ) : (
                <span className="truncate text-sm text-muted">{crumb.label}</span>
              )}
            </span>
          );
        })}
      </nav>

      {summary && (
        <span className="hidden flex-none text-xs whitespace-nowrap text-muted sm:inline">
          {summary}
        </span>
      )}
      {status}

      <div className="ml-auto flex flex-none items-center gap-[var(--s-4)]">
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
