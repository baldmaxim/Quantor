/**
 * Кнопка и её внешний вид.
 *
 * Вид отделён от элемента намеренно: тот же облик нужен ссылкам, которые ведут
 * себя как кнопки («Открыть», «Войти»), а ссылка обязана остаться ссылкой —
 * иначе теряются открытие в новой вкладке и её роль для программ чтения.
 */

import type { ButtonHTMLAttributes, ReactNode } from 'react';

import { cx } from './cx';

export type ButtonVariant = 'primary' | 'default' | 'ghost' | 'danger';

export interface IButtonLook {
  variant?: ButtonVariant;
  /** Компактный размер для панели инструментов рабочей области. */
  compact?: boolean;
  /** Квадратная кнопка под одну иконку: подписи нет, доступное имя обязательно. */
  iconOnly?: boolean;
  className?: string;
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

/**
 * Классы кнопки без самого элемента.
 *
 * Метка `ctl` нужна правилу тап-целей из base.css: `<a>` без `role="button"` под
 * него не попадает, и кнопка-ссылка на телефоне оставалась мельче 44px.
 */
export const buttonClassName = ({
  variant = 'default',
  compact = false,
  iconOnly = false,
  className,
}: IButtonLook = {}): string =>
  cx(
    'ctl press inline-flex items-center justify-center gap-[var(--s-3)] rounded-[var(--radius-sm)] border whitespace-nowrap',
    'text-sm select-none disabled:cursor-not-allowed disabled:opacity-45 disabled:shadow-none',
    compact ? 'h-[var(--h-ctl-ws)] text-xs' : 'h-[var(--h-ctl)]',
    iconOnly
      ? cx(
          'px-0',
          compact ? 'w-[var(--h-ctl-ws)]' : 'w-[var(--h-ctl)]',
          // Тап-цель растит кнопку по высоте; без ширины квадрат стал бы овалом.
          'max-md:h-[44px] max-md:w-[44px]',
        )
      : compact
        ? 'px-[var(--s-4)]'
        : 'px-[var(--s-5)]',
    BUTTON_VARIANTS[variant],
    className,
  );

/** Индикатор работы. Оформление в base.css: размер и цвет следуют за подписью. */
export const Spinner = ({ label, className }: { label?: string; className?: string }) =>
  label === undefined ? (
    <span aria-hidden="true" className={cx('spinner', className)} />
  ) : (
    <span role="status" aria-label={label} className={cx('spinner', className)} />
  );

interface IButtonBase extends ButtonHTMLAttributes<HTMLButtonElement>, IButtonLook {
  icon?: ReactNode;
  /**
   * Идёт работа: кнопка занята и не принимает повторное нажатие.
   *
   * Блокировка настоящая, а не только для программ чтения: главное действие
   * окна отправляет запрос, и второе нажатие создало бы второй проект.
   */
  loading?: boolean;
  /** Подпись на время работы. Без неё остаётся обычная, со значком слева. */
  loadingLabel?: string;
}

type IButtonProps = IButtonBase &
  // Иконочная кнопка без доступного имени — это кнопка без названия. Требуем его
  // типом, а не правилом линтера: так ошибка видна при сборке.
  ({ iconOnly?: false } | { iconOnly: true; 'aria-label': string });

const ROW = 'col-start-1 row-start-1 inline-flex items-center gap-[var(--s-3)]';

export const Button = ({
  variant = 'default',
  compact = false,
  iconOnly = false,
  icon,
  loading = false,
  loadingLabel,
  className,
  children,
  disabled,
  ...rest
}: IButtonProps) => (
  <button
    type="button"
    aria-busy={loading || undefined}
    disabled={disabled === true || loading}
    className={buttonClassName({ variant, compact, iconOnly, className })}
    {...rest}
  >
    {loadingLabel === undefined ? (
      <>
        {loading ? <Spinner /> : icon}
        {children}
      </>
    ) : (
      // Обе подписи участвуют в раскладке, видна одна: иначе кнопка сужается на
      // слове «Создаём…» и уводит за собой соседнюю «Отмена».
      <span className="grid place-items-center">
        <span aria-hidden="true" className={cx(ROW, 'invisible')}>
          {icon}
          {children}
        </span>
        <span aria-hidden="true" className={cx(ROW, 'invisible')}>
          <Spinner />
          {loadingLabel}
        </span>
        <span className={ROW}>
          {loading ? (
            <>
              <Spinner />
              {loadingLabel}
            </>
          ) : (
            <>
              {icon}
              {children}
            </>
          )}
        </span>
      </span>
    )}
  </button>
);
