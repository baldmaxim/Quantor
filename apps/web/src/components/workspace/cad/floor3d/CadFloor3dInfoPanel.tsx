'use client';

import { cx } from '@quantor/ui';
import { useEffect, useId, useRef, useState, type FC, type ReactNode } from 'react';

const LABEL = 'Высоты и отверстия плиты';

interface ICadFloor3dInfoPanelProps {
  readonly children: ReactNode;
}

const InfoIcon: FC = () => (
  <svg
    aria-hidden="true"
    viewBox="0 0 24 24"
    width="16"
    height="16"
    fill="none"
    stroke="currentColor"
    strokeWidth="1.8"
    strokeLinecap="round"
    strokeLinejoin="round"
  >
    <circle cx="12" cy="12" r="9" />
    <path d="M12 11v5" />
    <circle cx="12" cy="7.8" r="0.6" fill="currentColor" />
  </svg>
);

/**
 * Кнопка (i) верхней панели 3D-вида (иконочный ToolButton, прижата вправо) и всплывающая панель с содержимым (высоты листа, отверстия плиты).
 * Родитель верхней панели должен быть `relative`: всплывающая панель привязана к нему и на телефоне
 * не шире экрана. Закрытие - Esc, щелчок вне панели, повторное нажатие на (i). Содержимое остаётся
 * смонтированным при закрытии: незаконченная правка высот не теряется.
 */
export const CadFloor3dInfoPanel: FC<ICadFloor3dInfoPanelProps> = ({ children }) => {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const panel = useRef<HTMLDivElement>(null);
  const panelId = useId();

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (event: KeyboardEvent) => {
      if (event.key === 'Escape') setOpen(false);
    };
    const onDown = (event: PointerEvent) => {
      const target = event.target;
      if (!(target instanceof Node)) return;
      if (panel.current?.contains(target) || button.current?.contains(target)) return;
      setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    document.addEventListener('pointerdown', onDown);
    return () => {
      window.removeEventListener('keydown', onKey);
      document.removeEventListener('pointerdown', onDown);
    };
  }, [open]);

  return (
    <>
      <button
        ref={button}
        type="button"
        aria-label={LABEL}
        title={LABEL}
        aria-expanded={open}
        aria-controls={panelId}
        aria-haspopup="dialog"
        onClick={() => setOpen((current) => !current)}
        className={cx(
          'press ml-auto grid h-[var(--h-ctl-ws)] w-[30px] flex-none place-items-center rounded-[var(--radius-sm)]',
          open ? 'bg-accent-soft text-accent' : 'text-muted hover:bg-surface-muted hover:text-text',
        )}
      >
        <InfoIcon />
      </button>
      <div
        ref={panel}
        id={panelId}
        role="dialog"
        aria-label={LABEL}
        data-testid="floor3d-info-panel"
        hidden={!open}
        className="absolute top-full right-[var(--s-4)] left-[var(--s-4)] z-30 mt-[var(--s-2)] md:left-auto md:w-[360px]"
      >
        <div className="scroll-area flex max-h-[70dvh] flex-col gap-[var(--s-5)] overflow-auto overscroll-contain rounded-[var(--radius-md)] border border-border-strong bg-surface-raised p-[var(--s-5)] shadow-[var(--shadow-2)]">
          {children}
        </div>
      </div>
    </>
  );
};
