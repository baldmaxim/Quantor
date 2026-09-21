'use client';

import { useEffect, useId, useRef, useState, type ReactNode } from 'react';
import { createPortal } from 'react-dom';

import { cx } from './cx';
import {
  isolateBackground,
  trapTab,
  useEscape,
  usePresence,
  useReturnFocus,
} from './dialog-behavior';

/**
 * Модальное окно.
 *
 * Одно на все окна портала и контура управления: три копии разметки успели
 * разойтись отступами, оформлением списка и набором состояний, и ни в одной не
 * было ловушки фокуса.
 *
 * Карточка намеренно без собственного padding — отступы живут на секциях. Тогда
 * разделитель футера идёт во всю ширину без отрицательных полей, тело
 * прокручивается под закреплёнными шапкой и футером, а отступ под вырез экрана
 * складывается с ними, а не заменяет их.
 */

export type DialogSize = 'md' | 'lg';

interface IDialogProps {
  open: boolean;
  onClose: () => void;
  title: string;
  /** Пояснение под заголовком. Связывается с окном через aria-describedby. */
  description?: ReactNode;
  size?: DialogSize;
  /** Идёт работа, которую нельзя бросить: Escape и щелчок по подложке не закрывают. */
  busy?: boolean;
  /** Закреплённая полоса под шапкой: поиск, фильтр. Не уезжает при прокрутке. */
  toolbar?: ReactNode;
  /** Закреплённый футер. Внутрь кладут кнопки и DialogActions. */
  footer?: ReactNode;
  /** Дополнительные классы прокручиваемого тела. */
  bodyClassName?: string;
  /** Вызывается после анимации закрытия — момент, когда можно обнулить состояние. */
  onExited?: () => void;
  children: ReactNode;
}

const SIZES: Record<DialogSize, string> = {
  md: 'max-w-[620px]',
  lg: 'max-w-[720px]',
};

export const Dialog = ({
  open,
  onClose,
  title,
  description,
  size = 'md',
  busy = false,
  toolbar,
  footer,
  bodyClassName,
  onExited,
  children,
}: IDialogProps) => {
  const id = useId();
  const scrim = useRef<HTMLDivElement>(null);
  const card = useRef<HTMLDivElement>(null);

  const { mounted, state } = usePresence(open, onExited);
  const [host, setHost] = useState<HTMLElement | null>(null);

  // Портал берётся в эффекте: на сервере document нет, а компонент отрисовывается
  // и там тоже.
  useEffect(() => setHost(document.body), []);

  useEscape(mounted && !busy, onClose);

  // Порядок важен: React вызывает уборку эффектов в порядке их объявления.
  // Снятие inert обязано идти раньше возврата фокуса — иначе фокус ставится на
  // ещё «выключенный» фон, и браузер его молча игнорирует. В jsdom inert ничего
  // не делает, поэтому обмен местами виден только в настоящем браузере.
  useEffect(() => {
    if (!mounted || scrim.current === null) return;
    return isolateBackground(scrim.current);
  }, [mounted]);

  useReturnFocus(mounted);

  useEffect(() => {
    if (!mounted) return;

    // Кадром позже: autoFocus поля ставится при монтировании, и перебивать его
    // нельзя — иначе окно открывается с фокусом на пустом месте.
    const frame = requestAnimationFrame(() => {
      const node = card.current;
      if (node === null) return;
      if (node.contains(document.activeElement)) return;
      node.focus();
    });

    return () => cancelAnimationFrame(frame);
  }, [mounted]);

  if (!mounted || host === null) return null;

  return createPortal(
    <div
      ref={scrim}
      data-state={state}
      // На телефоне окно прижато к низу и во всю ширину: до кнопок внизу
      // дотягивается большой палец, а центрированная карточка с полями по краям
      // там только сужает поля ввода.
      className="dialog-scrim fixed inset-0 z-50 grid items-end justify-items-center sm:place-items-center sm:p-[var(--s-6)]"
      onMouseDown={(event) => {
        // Именно mousedown: окно не должно закрываться, когда выделение текста
        // начали внутри карточки, а отпустили за её краем.
        if (event.target === event.currentTarget && !busy) onClose();
      }}
    >
      <div
        ref={card}
        role="dialog"
        aria-modal="true"
        aria-labelledby={`${id}-title`}
        aria-describedby={description ? `${id}-description` : undefined}
        aria-busy={busy || undefined}
        tabIndex={-1}
        data-state={state}
        onKeyDown={(event) => {
          if (card.current === null) return;
          trapTab(card.current, event.nativeEvent);
        }}
        className={cx(
          'dialog-card flex max-h-[88dvh] w-full flex-col overflow-hidden outline-none',
          'rounded-t-[var(--radius-lg)] border border-border-strong bg-surface-raised shadow-[var(--shadow-2)]',
          // Вырез экрана: у карточки своего padding нет, поэтому это сложение,
          // а не замена отступа секций.
          'pb-[var(--safe-b)] pl-[var(--safe-l)] pr-[var(--safe-r)]',
          'sm:rounded-b-[var(--radius-lg)] sm:pb-0 sm:pl-0 sm:pr-0',
          SIZES[size],
        )}
      >
        <header className="flex flex-none flex-col gap-[var(--s-2)] px-[var(--s-6)] pt-[var(--s-6)] pb-[var(--s-5)] sm:px-[var(--s-7)] sm:pt-[var(--s-7)]">
          <h2 id={`${id}-title`} className="text-lg font-semibold">
            {title}
          </h2>
          {description && (
            <p id={`${id}-description`} className="text-sm text-muted">
              {description}
            </p>
          )}
        </header>

        {toolbar && (
          <div className="flex-none px-[var(--s-6)] pb-[var(--s-5)] sm:px-[var(--s-7)]">
            {toolbar}
          </div>
        )}

        <div
          className={cx(
            'scroll-area flex min-h-0 flex-1 flex-col gap-[var(--s-6)]',
            'px-[var(--s-6)] pb-[var(--s-6)] sm:px-[var(--s-7)]',
            bodyClassName,
          )}
        >
          {children}
        </div>

        {footer && (
          <footer className="flex flex-none flex-wrap items-center gap-[var(--s-4)] border-t border-border px-[var(--s-6)] py-[var(--s-5)] sm:px-[var(--s-7)] sm:py-[var(--s-6)]">
            {footer}
          </footer>
        )}
      </div>
    </div>,
    host,
  );
};

/**
 * Правая группа футера: отмена и главное действие.
 *
 * Разрушающее действие кладут первым ребёнком футера, до этой группы, — `ml-auto`
 * разводит их по краям, а при нехватке ширины переносится именно оно.
 */
export const DialogActions = ({ children }: { children: ReactNode }) => (
  <div className="ml-auto flex items-center gap-[var(--s-4)]">{children}</div>
);
