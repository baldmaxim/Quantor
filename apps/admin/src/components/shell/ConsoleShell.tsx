'use client';

import type { SessionResponse } from '@quantor/api-client';
import { ThemeToggle, cx } from '@quantor/ui';
import Link from 'next/link';
import { usePathname } from 'next/navigation';
import { useState, type ReactNode } from 'react';

import { env } from '@/lib/env';

/**
 * Оболочка контура управления.
 *
 * Десктоп-первый: таблицы прав, настроек и журнала не сжимаются до телефона без потери
 * смысла. На узком экране колонка разделов уезжает в выдвижную панель, а таблицы
 * прокручиваются вбок внутри себя — страница по горизонтали не едет.
 *
 * Разделы перечислены здесь, а не собираются из прав: администратор должен видеть контур
 * целиком, включая то, что пока пусто. Прятать раздел, потому что в нём нечего показать,
 * значит скрывать границу этапа.
 */

interface ISection {
  readonly href: string;
  readonly label: string;
  readonly hint: string;
}

const SECTIONS: readonly ISection[] = [
  { href: '/dashboard', label: 'Обзор', hint: 'Состояние установки' },
  { href: '/workspaces', label: 'Пространства', hint: 'Арендаторы' },
  { href: '/users', label: 'Пользователи и доступ', hint: 'Личности, членство, роли' },
  { href: '/settings', label: 'Настройки', hint: 'Управляемые параметры' },
  { href: '/feature-flags', label: 'Флаги возможностей', hint: 'Что показано, что скрыто' },
  { href: '/integrations', label: 'Интеграции', hint: 'TenderHUB' },
  { href: '/model-providers', label: 'Провайдеры моделей', hint: 'Реестр, без вызовов' },
  { href: '/jobs', label: 'Задания и воркеры', hint: 'Очередь и отказы' },
  { href: '/health', label: 'Состояние системы', hint: 'База, хранилище, зависимости' },
  { href: '/audit', label: 'Журнал', hint: 'Кто и что менял' },
];

interface IConsoleShellProps {
  session: SessionResponse;
  children: ReactNode;
}

export const ConsoleShell = ({ session, children }: IConsoleShellProps) => {
  const pathname = usePathname();
  const [navOpen, setNavOpen] = useState(false);

  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);
  const current = SECTIONS.find((section) => isActive(section.href));
  const actor = session.user?.display_name || session.user?.email || 'Администратор';

  return (
    <div className="flex h-dvh flex-col lg:flex-row">
      <nav
        aria-label="Разделы управления"
        className={cx(
          'safe-top flex-none border-border-strong bg-surface',
          'lg:flex lg:w-[248px] lg:flex-col lg:border-r',
          navOpen ? 'flex flex-col border-b' : 'hidden',
        )}
      >
        <div className="hidden h-[var(--h-topbar)] flex-none items-center gap-[var(--s-4)] border-b border-border px-[var(--s-5)] lg:flex">
          <span className="grid h-[28px] w-[28px] place-items-center rounded-[var(--radius-sm)] bg-accent text-sm font-bold text-accent-contrast">
            Q
          </span>
          <span className="text-sm font-semibold">Управление платформой</span>
        </div>

        <ul className="scroll-area flex min-h-0 flex-1 list-none flex-col gap-[2px] p-[var(--s-4)]">
          {SECTIONS.map((section) => (
            <li key={section.href}>
              <Link
                href={section.href}
                onClick={() => setNavOpen(false)}
                aria-current={isActive(section.href) ? 'page' : undefined}
                className={cx(
                  'press flex min-h-[40px] flex-col justify-center rounded-[var(--radius-sm)] px-[var(--s-4)] py-[var(--s-3)]',
                  isActive(section.href)
                    ? 'bg-surface-muted text-text'
                    : 'text-muted hover:bg-surface-muted hover:text-text',
                )}
              >
                <span className="text-sm">{section.label}</span>
                <span className="text-micro text-muted">{section.hint}</span>
              </Link>
            </li>
          ))}
        </ul>

        <div className="flex-none border-t border-border p-[var(--s-4)]">
          <a
            href={env.portalUrl}
            className="press block rounded-[var(--radius-sm)] px-[var(--s-4)] py-[var(--s-3)] text-sm text-muted hover:bg-surface-muted hover:text-text"
          >
            ← В портал
          </a>
        </div>
      </nav>

      <div className="flex min-h-0 min-w-0 flex-1 flex-col">
        <header className="flex h-[var(--h-topbar)] flex-none items-center gap-[var(--s-4)] border-b border-border-strong bg-surface px-[var(--s-5)]">
          <button
            type="button"
            onClick={() => setNavOpen((value) => !value)}
            aria-expanded={navOpen}
            aria-label="Разделы"
            className="press grid h-[32px] w-[32px] place-items-center rounded-[var(--radius-sm)] border border-border-control text-muted lg:hidden"
          >
            ☰
          </button>

          {/* Шапка — это обстановка, а не заголовок: название раздела принадлежит
              самой странице. Иначе одно и то же написано на экране дважды. */}
          <span className="min-w-0 truncate text-sm text-muted">
            Управление платформой{current ? ` · ${current.label}` : ''}
          </span>

          <div className="flex-1" />

          <span className="hidden max-w-[220px] truncate text-xs text-muted sm:block" title={actor}>
            {actor}
          </span>
          <ThemeToggle />
        </header>

        <main className="scroll-area safe-bottom min-h-0 flex-1 p-[var(--s-5)] lg:p-[var(--s-6)]">
          {children}
        </main>
      </div>
    </div>
  );
};
