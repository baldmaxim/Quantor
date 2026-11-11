'use client';

import { useCallback, useEffect, useId, useLayoutEffect, useRef, useState, type FC } from 'react';
import { createPortal } from 'react-dom';

import { StatusBadge } from '@/components/ui';
import { useWorkspaceStore } from '@/store/workspace';

import type { IWorkspaceCadConvert } from './types';
import type { IWorkspaceCadPipeline } from './useWorkspaceCadPipeline';
import { WorkspaceCadPipeline } from './WorkspaceCadPipeline';

export interface IWorkspacePipelineBadgeProps {
  readonly pipeline: IWorkspaceCadPipeline;
  /** Флаг `cad.export`: без него бейдж не показывается вовсе. */
  readonly cadOn: boolean;
  /** Запуск преобразования листа для окна обработки; `null` - лист не выбран. */
  readonly convert: IWorkspaceCadConvert | null;
  /** Разделы правой панели, в которые ведут действия шагов. */
  readonly openablePanels: readonly string[];
  /** Открывает раздел правой панели (режим CAD бейдж включает сам). */
  readonly onOpenPanel: (id: string) => void;
}

export const NOT_PROCESSED_LABEL = 'Лист не обрабатывался';

/** Зазор между бейджем и окном, px. */
const GAP_PX = 8;

/** Есть ли открытое окно, кроме самого всплывающего (подтверждение «Преобразовать заново»). */
const otherDialogOpen = (own: HTMLElement | null): boolean =>
  Array.from(document.querySelectorAll('[role="dialog"]')).some((node) => node !== own);

interface IPipelinePopoverProps {
  readonly pipeline: IWorkspaceCadPipeline;
  readonly convert: IWorkspaceCadConvert | null;
  readonly openablePanels: readonly string[];
  readonly trigger: HTMLElement | null;
  readonly titleId: string;
  /** `restoreFocus` - вернуть фокус на бейдж (закрытие с клавиатуры, крестиком, по действию). */
  readonly onClose: (restoreFocus: boolean) => void;
  readonly onOpenPanel: (id: string) => void;
}

/**
 * Окно обработки у бейджа. Выведено порталом в `body` и поставлено `fixed`: полоса вкладок над
 * рабочей областью прокручивается и обрезала бы окно. Положение - по бейджу, ставится прямо на
 * узел (размер известен после разметки). Ниже `md` окно растянуто с полями 16px по бокам.
 */
const PipelinePopover: FC<IPipelinePopoverProps> = ({
  pipeline,
  convert,
  openablePanels,
  trigger,
  titleId,
  onClose,
  onOpenPanel,
}) => {
  const element = useRef<HTMLDivElement>(null);

  useLayoutEffect(() => {
    const node = element.current;
    if (!node || !trigger) return undefined;
    const apply = () => {
      const box = trigger.getBoundingClientRect();
      node.style.setProperty('--pop-top', `${box.bottom + GAP_PX}px`);
      node.style.setProperty('--pop-right', `${Math.max(16, window.innerWidth - box.right)}px`);
    };
    apply();
    window.addEventListener('resize', apply);
    return () => window.removeEventListener('resize', apply);
  }, [trigger]);

  // Фокус - в окно при открытии.
  useEffect(() => {
    element.current?.focus();
  }, []);

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      // Esc внутри подтверждения закрывает только его: окно обработки остаётся.
      if (event.key !== 'Escape' || otherDialogOpen(element.current)) return;
      onClose(true);
    };
    const onPointerDown = (event: PointerEvent) => {
      if (otherDialogOpen(element.current)) return;
      const target = event.target;
      if (!(target instanceof Node)) return;
      // Бейдж переключает окно сам: иначе нажатие закрыло бы его, а клик открыл заново.
      if (element.current?.contains(target) || trigger?.contains(target)) return;
      onClose(false);
    };
    document.addEventListener('keydown', onKeyDown);
    document.addEventListener('pointerdown', onPointerDown, true);
    return () => {
      document.removeEventListener('keydown', onKeyDown);
      document.removeEventListener('pointerdown', onPointerDown, true);
    };
  }, [onClose, trigger]);

  // Окно монтируется только по нажатию на бейдж, то есть в браузере: document есть.
  return createPortal(
    <div
      ref={element}
      role="dialog"
      aria-labelledby={titleId}
      tabIndex={-1}
      data-testid="pipeline-popover"
      className="scroll-area animate-rise fixed top-[var(--pop-top)] right-[max(16px,var(--safe-r))] left-[max(16px,var(--safe-l))] z-50 flex max-h-[70dvh] flex-col gap-[var(--s-4)] overflow-y-auto overscroll-contain rounded-[var(--radius-md)] border border-border-strong bg-surface-raised p-[var(--s-5)] shadow-[var(--shadow-2)] outline-none md:right-[var(--pop-right)] md:left-auto md:w-[min(360px,calc(100vw-32px))]"
    >
      <header className="flex min-w-0 items-center justify-between gap-[var(--s-3)]">
        <h3 id={titleId} className="m-0 text-sm font-medium">
          Обработка листа
        </h3>
        <button
          type="button"
          aria-label="Закрыть"
          onClick={() => onClose(true)}
          className="press grid h-[44px] w-[44px] shrink-0 touch-manipulation place-items-center rounded-[var(--radius-xs)] text-muted hover:bg-surface-muted hover:text-text md:h-8 md:w-8"
        >
          <svg
            aria-hidden="true"
            viewBox="0 0 24 24"
            className="h-[14px] w-[14px]"
            fill="none"
            stroke="currentColor"
            strokeWidth="2"
            strokeLinecap="round"
          >
            <path d="M6 6l12 12M18 6L6 18" />
          </svg>
        </button>
      </header>
      <WorkspaceCadPipeline
        pipeline={pipeline}
        convert={convert}
        openablePanels={openablePanels}
        onOpenPanel={onOpenPanel}
      />
    </div>,
    document.body,
  );
};

/**
 * Итог обработки листа в шапке рабочей области; нажатие открывает окно со статусами шагов и
 * действиями (бывший раздел «Обработка» правой панели). Действие, ведущее в раздел панели,
 * включает режим CAD, открывает раздел и закрывает окно.
 */
export const WorkspacePipelineBadge: FC<IWorkspacePipelineBadgeProps> = ({
  pipeline,
  cadOn,
  convert,
  openablePanels,
  onOpenPanel,
}) => {
  const setMode = useWorkspaceStore((state) => state.setMode);
  const scaleTool = useWorkspaceStore((state) => state.tool === 'scale');
  const [open, setOpen] = useState(false);
  const [trigger, setTrigger] = useState<HTMLButtonElement | null>(null);
  const wasScale = useRef(scaleTool);
  const titleId = useId();

  const close = useCallback(
    (restoreFocus: boolean) => {
      setOpen(false);
      if (restoreFocus) trigger?.focus();
    },
    [trigger],
  );

  // «Откалибровать» включает инструмент «Масштаб»: окно закрывается, чтобы кликать по чертежу.
  useEffect(() => {
    if (scaleTool && !wasScale.current && open) setOpen(false);
    wasScale.current = scaleTool;
  }, [scaleTool, open]);

  if (!cadOn || pipeline.isPending || pipeline.isError) return null;
  const tone = pipeline.summary?.tone ?? 'neutral';
  const label = pipeline.summary?.label ?? NOT_PROCESSED_LABEL;
  return (
    <>
      <button
        ref={setTrigger}
        type="button"
        onClick={() => setOpen((value) => !value)}
        aria-haspopup="dialog"
        aria-expanded={open}
        aria-label={`Обработка листа: ${label}`}
        className="inline-flex min-h-[44px] touch-manipulation items-center md:min-h-8"
      >
        <StatusBadge tone={tone}>{label}</StatusBadge>
      </button>
      {open && (
        <PipelinePopover
          pipeline={pipeline}
          convert={convert}
          openablePanels={openablePanels}
          trigger={trigger}
          titleId={titleId}
          onClose={close}
          onOpenPanel={(id) => {
            setMode('cad');
            onOpenPanel(id);
            close(false);
          }}
        />
      )}
    </>
  );
};
