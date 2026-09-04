'use client';

import { useEffect, useRef, useState, type RefObject } from 'react';

import { cx } from '@/components/ui';

/**
 * Разделитель панелей.
 *
 * Тянется мышью и стрелками с клавиатуры: рабочей областью пользуются подолгу,
 * и подобрать ширину панели под конкретный чертёж — обычное действие.
 *
 * Во время перетаскивания ширина идёт мимо состояния React — прямо в CSS-переменную
 * контейнера. Иначе каждое движение мыши перерисовывало бы обе панели вместе со всем
 * их содержимым. В состояние ширина попадает один раз, когда кнопку отпустили.
 */

interface ISplitterProps {
  /** Текущая ширина панели в пикселях. */
  width: number;
  min: number;
  max: number;
  /** С какой стороны от разделителя находится панель. */
  side: 'left' | 'right';
  label: string;
  onResize: (width: number) => void;
  /** Контейнер, в CSS-переменную которого пишется ширина во время перетаскивания. */
  previewTarget: RefObject<HTMLElement | null>;
  previewVariable: string;
}

const KEYBOARD_STEP = 16;

export const Splitter = ({
  width,
  min,
  max,
  side,
  label,
  onResize,
  previewTarget,
  previewVariable,
}: ISplitterProps) => {
  const [dragging, setDragging] = useState(false);
  const latest = useRef(width);

  // Ручная мемоизация здесь не нужна: компилятор React делает её сам, а useCallback
  // с зависимостью-ссылкой он оптимизировать отказывается.
  const clamp = (value: number) => Math.min(Math.max(value, min), max);

  // К ссылке обращаемся только из обработчиков событий: во время отрисовки её значение
  // читать нельзя, да и незачем.
  const preview = (value: number) => {
    previewTarget.current?.style.setProperty(previewVariable, `${value}px`);
  };

  const handlePointerDown = (event: React.PointerEvent<HTMLDivElement>) => {
    event.preventDefault();
    const startX = event.clientX;
    const startWidth = width;
    latest.current = startWidth;
    setDragging(true);

    const move = (moveEvent: PointerEvent) => {
      const delta = moveEvent.clientX - startX;
      const next = clamp(startWidth + (side === 'left' ? delta : -delta));
      latest.current = next;
      preview(next);
    };

    const up = () => {
      window.removeEventListener('pointermove', move);
      window.removeEventListener('pointerup', up);
      setDragging(false);
      onResize(latest.current);
    };

    window.addEventListener('pointermove', move);
    window.addEventListener('pointerup', up);
  };

  const handleKeyDown = (event: React.KeyboardEvent<HTMLDivElement>) => {
    const direction = event.key === 'ArrowLeft' ? -1 : event.key === 'ArrowRight' ? 1 : 0;
    if (direction === 0) return;

    event.preventDefault();
    const next = clamp(width + direction * KEYBOARD_STEP * (side === 'left' ? 1 : -1));
    preview(next);
    onResize(next);
  };

  // Пока тянут разделитель, курсор не должен превращаться в текстовый над панелями.
  useEffect(() => {
    if (!dragging) return;

    const previous = document.body.style.cursor;
    document.body.style.cursor = 'col-resize';
    document.body.style.userSelect = 'none';

    return () => {
      document.body.style.cursor = previous;
      document.body.style.userSelect = '';
    };
  }, [dragging]);

  return (
    <div
      role="separator"
      aria-orientation="vertical"
      aria-label={label}
      aria-valuenow={Math.round(width)}
      aria-valuemin={min}
      aria-valuemax={max}
      tabIndex={0}
      onPointerDown={handlePointerDown}
      onKeyDown={handleKeyDown}
      className={cx(
        'relative w-[3px] flex-none cursor-col-resize bg-border-strong transition-colors',
        'hover:bg-accent focus-visible:bg-accent',
        dragging && 'bg-accent',
      )}
    >
      {/* Полоса шириной 3 px слишком тонка, чтобы в неё попасть: расширяем зону захвата,
          не расширяя видимую линию. */}
      <span aria-hidden="true" className="absolute inset-y-0 -left-[3px] w-[9px]" />
    </div>
  );
};
