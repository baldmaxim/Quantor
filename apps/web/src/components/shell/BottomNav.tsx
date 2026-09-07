'use client';

import Link from 'next/link';
import { usePathname } from 'next/navigation';
import type { ComponentType, SVGProps } from 'react';

import { cx } from '@/components/ui';
import { IconProjects, IconSettings } from '@/components/ui/icons';
import { useFeatures } from '@/lib/queries';

/**
 * Навигация на телефоне.
 *
 * Вертикальная рейка на узком экране съедала бы шестую часть ширины, а до её верха
 * ещё и не дотянуться большим пальцем. Поэтому на телефоне разделы уезжают вниз,
 * где до них дотягиваются, не перехватывая телефон.
 *
 * Пункты те же, что в рейке, но без разделов следующих этапов: на телефоне место
 * дороже, а показывать четыре выключенных пункта из шести — издевательство.
 */

interface NavItem {
  readonly href: string;
  readonly label: string;
  readonly Icon: ComponentType<SVGProps<SVGSVGElement>>;
  readonly feature?: string;
}

const ITEMS: readonly NavItem[] = [
  { href: '/projects', label: 'Проекты', Icon: IconProjects },
  { href: '/settings', label: 'Настройки', Icon: IconSettings },
];

export const BottomNav = () => {
  const pathname = usePathname();
  const features = useFeatures();

  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`);
  const isEnabled = (item: NavItem) => !item.feature || features[item.feature] === true;

  return (
    <nav
      aria-label="Разделы портала"
      style={{ viewTransitionName: 'shell-bottomnav' }}
      className="safe-bottom sticky bottom-0 z-30 flex flex-none border-t border-border-strong bg-surface md:hidden"
    >
      {ITEMS.filter(isEnabled).map(({ href, label, Icon }) => {
        const active = isActive(href);

        return (
          <Link
            key={href}
            href={href}
            aria-current={active ? 'page' : undefined}
            className={cx(
              'press relative flex min-h-[var(--h-bottom-nav)] flex-1 flex-col items-center justify-center gap-[var(--s-2)]',
              active ? 'text-accent' : 'text-muted',
            )}
          >
            <Icon width={20} height={20} />
            <span className="text-micro">{label}</span>
            {active && (
              <span
                aria-hidden="true"
                className="absolute top-0 h-[2px] w-[36px] rounded-full bg-accent"
              />
            )}
          </Link>
        );
      })}
    </nav>
  );
};
