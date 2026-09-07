'use client';

import { cx } from '@/components/ui';
import { toggleTheme, useTheme } from '@/lib/theme';

/**
 * Переключатель темы.
 *
 * Обе иконки нарисованы всегда и разведены поворотом и прозрачностью: подмена одного
 * элемента другим даёт скачок, а перекрёстный поворот читается как одно движение.
 *
 * Кнопка стоит в шапке, а не только в настройках: тему меняют по освещению в комнате,
 * а не раз в жизни, и ходить за этим в отдельный раздел неудобно.
 */
export const ThemeToggle = ({ className }: { className?: string }) => {
  const theme = useTheme();
  const dark = theme === 'dark';

  return (
    <button
      type="button"
      onClick={() => toggleTheme()}
      aria-label={dark ? 'Включить светлую тему' : 'Включить тёмную тему'}
      title={dark ? 'Светлая тема' : 'Тёмная тема'}
      className={cx(
        'press relative grid h-[var(--h-ctl)] w-[var(--h-ctl)] place-items-center',
        'rounded-[var(--radius-sm)] border border-transparent text-muted',
        'hover:border-border-control hover:bg-surface-muted hover:text-text',
        className,
      )}
    >
      <Sun
        className={cx(
          'absolute transition-all duration-[var(--dur-base)] ease-[var(--ease-out)]',
          dark ? 'scale-50 rotate-90 opacity-0' : 'scale-100 rotate-0 opacity-100',
        )}
      />
      <Moon
        className={cx(
          'absolute transition-all duration-[var(--dur-base)] ease-[var(--ease-out)]',
          dark ? 'scale-100 rotate-0 opacity-100' : 'scale-50 -rotate-90 opacity-0',
        )}
      />
    </button>
  );
};

const Sun = ({ className }: { className?: string }) => (
  <svg
    aria-hidden="true"
    viewBox="0 0 24 24"
    width="17"
    height="17"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.7"
    strokeLinecap="round"
    className={className}
  >
    <circle cx="12" cy="12" r="4" />
    <path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4" />
  </svg>
);

const Moon = ({ className }: { className?: string }) => (
  <svg
    aria-hidden="true"
    viewBox="0 0 24 24"
    width="17"
    height="17"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.7"
    strokeLinecap="round"
    strokeLinejoin="round"
    className={className}
  >
    <path d="M20 14.5A8.5 8.5 0 019.5 4a8.5 8.5 0 1010.5 10.5z" />
  </svg>
);
