'use client';

import { useRef, useState, type DragEvent, type FC } from 'react';

import { cx } from '@/components/ui';

interface ICadPdfDropzoneProps {
  onPick: (file: File) => void;
  disabled?: boolean;
}

/**
 * Приём одного PDF перетаскиванием или выбором на диске.
 * Другие типы файлов выбрать нельзя; окончательную проверку делает сервер.
 */
export const CadPdfDropzone: FC<ICadPdfDropzoneProps> = ({ onPick, disabled = false }) => {
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files[0];
    if (!disabled && file) onPick(file);
  };

  return (
    <div
      onDragOver={(event) => {
        event.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={handleDrop}
      className={cx(
        'flex flex-col items-center gap-[var(--s-3)] rounded-[var(--radius-md)] border border-dashed px-[var(--s-6)] py-[var(--s-7)] text-center transition-colors',
        dragging ? 'border-accent bg-accent-soft' : 'border-border-strong',
        disabled && 'opacity-50',
      )}
    >
      <p className="text-sm">Перетащите PDF сюда</p>
      <button
        type="button"
        disabled={disabled}
        onClick={() => input.current?.click()}
        className="min-h-[44px] px-[var(--s-5)] text-sm text-accent underline underline-offset-4 disabled:no-underline"
      >
        или выберите на диске
      </button>
      <input
        ref={input}
        type="file"
        accept="application/pdf,.pdf"
        className="visually-hidden"
        aria-label="Выбрать PDF"
        disabled={disabled}
        onChange={(event) => {
          const file = event.target.files?.[0];
          if (file) onPick(file);
          // Сброс значения: повторный выбор того же файла иначе не вызовет событие.
          event.target.value = '';
        }}
      />
    </div>
  );
};
