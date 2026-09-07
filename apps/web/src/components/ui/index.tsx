/**
 * Примитивы интерфейса.
 *
 * Собраны в одном файле намеренно: их немного, они мелкие и меняются вместе.
 * Как только какой-то из них обрастёт логикой, он переедет в отдельный модуль.
 *
 * Цвета — только через токены. Хардкод здесь означает, что тёмная тема развалится
 * ровно в этом месте и никто этого не заметит до демонстрации.
 */

import type { ButtonHTMLAttributes, InputHTMLAttributes, ReactNode } from 'react';

export const cx = (...parts: (string | false | null | undefined)[]): string =>
  parts.filter(Boolean).join(' ');

/* -------------------------------------------------------------------------- кнопка */

type ButtonVariant = 'primary' | 'default' | 'ghost' | 'danger';

interface IButtonProps extends ButtonHTMLAttributes<HTMLButtonElement> {
  variant?: ButtonVariant;
  /** Компактный размер для панели инструментов рабочей области. */
  compact?: boolean;
  icon?: ReactNode;
}

const BUTTON_VARIANTS: Record<ButtonVariant, string> = {
  primary:
    'bg-accent text-accent-contrast border-accent font-medium shadow-[var(--shadow-1)] hover:bg-accent-hover hover:border-accent-hover active:bg-accent-active active:shadow-none',
  default:
    'bg-surface text-text border-border-control hover:bg-surface-muted hover:border-border-strong active:bg-surface-sunken',
  ghost: 'bg-transparent text-muted border-transparent hover:bg-surface-muted hover:text-text',
  danger:
    'bg-transparent text-danger border-border-control hover:bg-danger-soft hover:border-danger',
};

export const Button = ({
  variant = 'default',
  compact = false,
  icon,
  className,
  children,
  ...rest
}: IButtonProps) => (
  <button
    type="button"
    className={cx(
      'press inline-flex items-center justify-center gap-[var(--s-3)] rounded-[var(--radius-sm)] border px-[var(--s-5)] whitespace-nowrap',
      'text-sm select-none disabled:cursor-not-allowed disabled:opacity-45 disabled:shadow-none',
      compact ? 'h-[var(--h-ctl-ws)] px-[var(--s-4)] text-xs' : 'h-[var(--h-ctl)]',
      BUTTON_VARIANTS[variant],
      className,
    )}
    {...rest}
  >
    {icon}
    {children}
  </button>
);

/* -------------------------------------------------------------------- поле поиска */

interface ISearchInputProps extends Omit<InputHTMLAttributes<HTMLInputElement>, 'type'> {
  label: string;
  /** Показывает крестик очистки, когда в поле что-то введено. */
  onClear?: () => void;
}

export const SearchInput = ({ label, className, onClear, ...rest }: ISearchInputProps) => {
  const filled = String(rest.value ?? '').length > 0;

  return (
    <label className={cx('group relative inline-flex items-center', className)}>
      <span className="visually-hidden">{label}</span>
      <svg
        aria-hidden="true"
        viewBox="0 0 24 24"
        className={cx(
          'pointer-events-none absolute left-[var(--s-4)] h-[14px] w-[14px]',
          'transition-colors duration-[var(--dur-fast)]',
          filled ? 'text-text' : 'text-muted',
        )}
        fill="none"
        stroke="currentColor"
        strokeWidth="1.7"
      >
        <circle cx="11" cy="11" r="7" />
        <path d="M20 20l-3.5-3.5" />
      </svg>
      <input
        type="search"
        placeholder={label}
        className={cx(
          // Заливка светлее шапки, а не темнее: тёмный колодец на тёмном фоне виден
          // только за счёт рамки, и рамку приходится делать яркой. Светлое поле
          // читается само, и рамке остаётся быть тихой.
          'h-[var(--h-ctl)] w-full rounded-[var(--radius-sm)] border border-border-control bg-surface-muted',
          'pl-[calc(var(--s-6)+var(--s-5))] text-sm text-text',
          filled ? 'pr-[calc(var(--s-6)+var(--s-4))]' : 'pr-[var(--s-5)]',
          'placeholder:text-muted',
          // Крестик очистки — своя кнопка: встроенный у type="search" есть не во всех
          // браузерах и не красится темой.
          '[&::-webkit-search-cancel-button]:hidden',
          // Граница подсвечивается акцентом при наведении и фокусе: поле должно
          // отзываться раньше, чем в него начали печатать.
          'transition-[border-color,box-shadow,background-color] duration-[var(--dur-fast)] ease-[var(--ease-out)]',
          'hover:border-border-strong focus:border-accent focus:bg-surface-raised focus:outline-none',
          'focus:shadow-[0_0_0_3px_var(--accent-soft)]',
        )}
        {...rest}
      />
      {filled && onClear && (
        <button
          type="button"
          onClick={onClear}
          aria-label={`Очистить: ${label}`}
          className={cx(
            'press absolute right-[var(--s-3)] grid h-[22px] w-[22px] place-items-center',
            'rounded-[var(--radius-xs)] text-muted hover:bg-surface-muted hover:text-text',
          )}
        >
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            className="h-[12px] w-[12px]"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
          >
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      )}
    </label>
  );
};

/* ------------------------------------------------------------------------ бейджи */

export type BadgeTone = 'neutral' | 'accent' | 'success' | 'warning' | 'danger';

const BADGE_TONES: Record<BadgeTone, string> = {
  neutral: 'text-muted bg-surface-muted border-border',
  accent: 'text-accent bg-accent-soft border-accent-soft',
  success: 'text-success bg-success-soft border-success-soft',
  warning: 'text-warning bg-warning-soft border-warning-soft',
  danger: 'text-danger bg-danger-soft border-danger-soft',
};

interface IStatusBadgeProps {
  tone?: BadgeTone;
  children: ReactNode;
  /** Точка перед текстом. Убирается там, где бейдж и так один в строке. */
  dot?: boolean;
}

export const StatusBadge = ({ tone = 'neutral', dot = true, children }: IStatusBadgeProps) => (
  <span
    className={cx(
      'inline-flex items-center gap-[var(--s-3)] rounded-full border px-[var(--s-4)] py-[1px]',
      'text-micro font-medium whitespace-nowrap',
      // Состояние задания меняется на глазах: без перехода бейдж «моргает».
      'transition-colors duration-[var(--dur-base)] ease-[var(--ease-out)]',
      BADGE_TONES[tone],
    )}
  >
    {dot && <span aria-hidden="true" className="h-[6px] w-[6px] rounded-full bg-current" />}
    {children}
  </span>
);

/* ------------------------------------------------------------------- полоса хода */

interface IProgressRowProps {
  /** Доля выполнения от 0 до 1. null — работа идёт, но доля неизвестна. */
  value: number | null;
  label: string;
}

export const ProgressRow = ({ value, label }: IProgressRowProps) => {
  const percent = value === null ? null : Math.round(Math.min(Math.max(value, 0), 1) * 100);

  return (
    <div className="flex flex-col gap-[var(--s-2)]">
      <div className="flex items-baseline justify-between text-xs text-muted">
        <span>{label}</span>
        {/* Выдуманных процентов не показываем: если доли нет, так и пишем. */}
        <span className="tabular">{percent === null ? 'выполняется' : `${percent} %`}</span>
      </div>
      <div
        role="progressbar"
        aria-valuemin={0}
        aria-valuemax={100}
        aria-valuenow={percent ?? undefined}
        aria-label={label}
        className="h-[4px] overflow-hidden rounded-full bg-surface-sunken"
      >
        <div
          className={cx(
            'h-full origin-left bg-accent',
            'transition-[width] duration-[var(--dur-slow)] ease-[var(--ease-out)]',
            // Долю не знаем — показываем движение, а не выдуманный процент.
            percent === null && 'animate-pulse',
          )}
          style={{ width: percent === null ? '35%' : `${percent}%` }}
        />
      </div>
    </div>
  );
};

/* --------------------------------------------------------------- пустые состояния */

interface IEmptyStateProps {
  title: string;
  description?: ReactNode;
  action?: ReactNode;
  compact?: boolean;
}

export const EmptyState = ({ title, description, action, compact = false }: IEmptyStateProps) => (
  <div
    className={cx(
      'animate-rise flex flex-col items-center gap-[var(--s-4)] rounded-[var(--radius-md)] border border-dashed border-border-strong text-center',
      compact ? 'px-[var(--s-6)] py-[var(--s-7)]' : 'px-[var(--s-8)] py-[calc(var(--s-8)*1.5)]',
    )}
  >
    <p className="text-lg font-medium">{title}</p>
    {description && <p className="max-w-[52ch] text-sm text-muted">{description}</p>}
    {action}
  </div>
);

interface IErrorStateProps {
  title: string;
  code?: string | null;
  description?: ReactNode;
  onRetry?: () => void;
}

export const ErrorState = ({ title, code, description, onRetry }: IErrorStateProps) => (
  <div
    role="alert"
    className="animate-rise flex flex-col items-start gap-[var(--s-4)] rounded-[var(--radius-md)] border border-danger-soft bg-danger-soft px-[var(--s-6)] py-[var(--s-5)]"
  >
    <div className="flex items-center gap-[var(--s-4)]">
      <span className="text-md font-medium text-danger">{title}</span>
      {/* Код ошибки стабилен и пригоден для поиска в логах, в отличие от текста. */}
      {code && <span className="mono text-xs text-muted">{code}</span>}
    </div>
    {description && <p className="text-sm text-text">{description}</p>}
    {onRetry && (
      <Button onClick={onRetry} variant="default">
        Повторить
      </Button>
    )}
  </div>
);

/* ------------------------------------------------------------------- скелетоны */

export const Skeleton = ({ className }: { className?: string }) => (
  <div aria-hidden="true" className={cx('skeleton', className)} />
);

export const SkeletonRows = ({ rows = 5 }: { rows?: number }) => (
  <div className="flex flex-col" role="status" aria-label="Загрузка">
    {Array.from({ length: rows }, (_, index) => (
      <div
        key={index}
        className="flex h-[var(--h-row)] items-center gap-[var(--s-6)] border-b border-border px-[var(--s-6)] last:border-b-0"
      >
        <Skeleton className="h-[10px] flex-1" />
        <Skeleton className="h-[10px] w-[64px]" />
        <Skeleton className="h-[10px] w-[96px]" />
      </div>
    ))}
  </div>
);

/* --------------------------------------------------------- секция инспектора */

interface IInspectorSectionProps {
  title: string;
  aside?: ReactNode;
  children: ReactNode;
}

export const InspectorSection = ({ title, aside, children }: IInspectorSectionProps) => (
  <section className="border-t border-border pt-[var(--s-5)] first:border-t-0 first:pt-0">
    <h3 className="mb-[var(--s-4)] flex items-center gap-[var(--s-3)] text-micro font-semibold tracking-[0.06em] text-muted uppercase">
      {title}
      {aside}
    </h3>
    {children}
  </section>
);

/** Пара «подпись — значение». Значение моноширинное: это данные, а не текст. */
export const Field = ({ label, children }: { label: string; children: ReactNode }) => (
  <>
    <dt className="text-xs text-muted">{label}</dt>
    <dd className="mono m-0 text-xs break-words">{children}</dd>
  </>
);
