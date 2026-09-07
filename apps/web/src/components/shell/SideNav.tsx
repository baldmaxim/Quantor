'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { ComponentType, SVGProps } from 'react';

import { AccountMenu } from '@/components/shell/AccountMenu';
import { cx } from '@/components/ui';
import {
  IconModels,
  IconProjects,
  IconReports,
  IconSettings,
  IconTemplates,
} from '@/components/ui/icons';
import { useFeatures } from '@/lib/queries';

/**
 * Навигационная рейка.
 *
 * Разделы, которых ещё нет, показаны выключенными и подписаны этапом. Прятать их
 * нельзя — пользователь должен видеть, куда движется продукт; делать вид, что они
 * работают, тоже нельзя.
 *
 * Что выключено, решают флаги возможностей API, а не этот файл: иначе при подключении
 * раздела обещания на экране разойдутся с поведением сервера.
 */

interface NavItem {
  readonly href: string;
  readonly label: string;
  readonly Icon: ComponentType<SVGProps<SVGSVGElement>>;
  /** Флаг возможности. Пока он выключен, пункт неактивен. */
  readonly feature?: string;
  readonly stage?: string;
}

// У «Проектов» нет флага намеренно: это сам продукт. Если сделать его зависимым от
// ответа сервера, при недоступном API навигация целиком станет неактивной — и уйти
// со страницы ошибки будет некуда.
const PRIMARY: readonly NavItem[] = [
  { href: '/projects', label: 'Проекты', Icon: IconProjects },
  {
    href: '/templates',
    label: 'Шаблоны',
    Icon: IconTemplates,
    feature: 'takeoff.manual',
    stage: 'Этап 2',
  },
  {
    href: '/models',
    label: 'Модели',
    Icon: IconModels,
    feature: 'models.gateway',
    stage: 'Этап 2',
  },
  { href: '/reports', label: 'Отчёты', Icon: IconReports, feature: 'reports', stage: 'Этап 2' },
];

const SETTINGS: NavItem = { href: '/settings', label: 'Настройки', Icon: IconSettings };

interface IRailButtonProps {
  item: NavItem;
  active: boolean;
  enabled: boolean;
}

const RailButton = ({ item, active, enabled }: IRailButtonProps) => {
  const { Icon } = item;
  const title = enabled ? item.label : `${item.label} — ${item.stage ?? 'позже'}`;
  const shared = cx(
    'press relative grid h-[36px] w-[36px] place-items-center rounded-[var(--radius-sm)]',
    active ? 'bg-surface-muted text-accent' : 'text-muted',
    enabled && !active && 'hover:bg-surface-muted hover:text-text',
    !enabled && 'opacity-40',
  );

  if (!enabled) {
    return (
      <span className={shared} title={title} aria-disabled="true" aria-label={title}>
        <Icon />
      </span>
    );
  }

  return (
    <Link
      href={item.href}
      className={shared}
      title={title}
      aria-label={item.label}
      aria-current={active ? 'page' : undefined}
    >
      {active && (
        <span
          aria-hidden="true"
          // Метка активного раздела переезжает вместе с выбором: общее имя перехода
          // заставляет браузер анимировать её как один и тот же объект.
          style={{ viewTransitionName: 'nav-marker' }}
          className="absolute top-[8px] bottom-[8px] -left-[8px] w-[2px] rounded-full bg-accent"
        />
      )}
      <Icon />
    </Link>
  );
};

export const SideNav = () => {
  const pathname = usePathname();
  const features = useFeatures();

  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);
  const isEnabled = (item: NavItem) => !item.feature || features[item.feature] === true;

  return (
    <nav
      aria-label="Разделы портала"
      style={{ viewTransitionName: 'shell-sidenav' }}
      className="safe-top hidden w-[var(--w-rail)] flex-none flex-col items-center border-r border-border-strong bg-surface md:flex"
    >
      {/* Знак стоит в полосе высотой с шапку и по её центру: прижатый к самому краю
          окна, он выглядел обрезанным и не совпадал по линии с хлебными крошками. */}
      <div className="flex h-[var(--h-topbar)] flex-none items-center">
        <Link
          href="/projects"
          aria-label="Quantor — к списку проектов"
          className="press grid h-[32px] w-[32px] place-items-center rounded-[var(--radius-sm)] bg-accent text-lg font-bold text-accent-contrast shadow-[var(--shadow-1)]"
        >
          Q
        </Link>
      </div>

      <div className="flex min-h-0 flex-1 flex-col items-center gap-[var(--s-4)] pt-[var(--s-4)] pb-[var(--s-5)]">
        {PRIMARY.map((item) => (
          <RailButton
            key={item.href}
            item={item}
            active={isActive(item.href)}
            enabled={isEnabled(item)}
          />
        ))}

        <div className="flex-1" />

        <RailButton item={SETTINGS} active={isActive(SETTINGS.href)} enabled />
        <AccountMenu />
      </div>
    </nav>
  );
};
