'use client';

import { useRef, useState, type DragEvent } from 'react';

import { StatusBadge, cx } from '@/components/ui';
import { IconBim, IconPdf, IconZip } from '@/components/ui/icons';
import { formatBytes } from '@/lib/format';
import { ACCEPT_ATTRIBUTE, extensionOf, isAccepted } from '@/lib/upload';

/**
 * Приём файлов перетаскиванием и выбором.
 *
 * Каждому типу подписано, что с ним произойдёт: пакет импортируется, PDF просто ляжет
 * в хранилище, BIM-модель сохранится без обработки. Обещать распознавание там, где его
 * нет, нельзя — иначе пользователь будет ждать результата, который не появится.
 */

export interface PickedFile {
  readonly file: File;
  readonly accepted: boolean;
}

interface IFileDropzoneProps {
  files: readonly PickedFile[];
  onAdd: (files: File[]) => void;
  onRemove: (index: number) => void;
  disabled?: boolean;
}

const CAPABILITY: Record<string, { text: string; tone: 'accent' | 'warning' | 'neutral' }> = {
  zip: { text: 'Импортировать', tone: 'accent' },
  pdf: { text: 'Сохранить, распознавание — на следующем этапе', tone: 'warning' },
  rvt: { text: 'Сохранить, обработчик не подключён', tone: 'neutral' },
  nwd: { text: 'Сохранить, обработчик не подключён', tone: 'neutral' },
  nwc: { text: 'Сохранить, обработчик не подключён', tone: 'neutral' },
  ifc: { text: 'Сохранить, обработчик не подключён', tone: 'neutral' },
};

const ICONS: Record<string, typeof IconPdf> = {
  zip: IconZip,
  pdf: IconPdf,
  rvt: IconBim,
  nwd: IconBim,
  nwc: IconBim,
  ifc: IconBim,
};

export const FileDropzone = ({ files, onAdd, onRemove, disabled = false }: IFileDropzoneProps) => {
  const [dragging, setDragging] = useState(false);
  const input = useRef<HTMLInputElement>(null);

  const handleDrop = (event: DragEvent<HTMLDivElement>) => {
    event.preventDefault();
    setDragging(false);
    if (disabled) return;
    onAdd(Array.from(event.dataTransfer.files));
  };

  return (
    <div className="flex flex-col gap-[var(--s-4)]">
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
        <p className="text-sm">Перетащите файлы сюда</p>
        <p className="text-xs text-muted">
          ZIP-пакет распознавалки, PDF, а также RVT, NWD, NWC и IFC на хранение
        </p>
        <button
          type="button"
          disabled={disabled}
          onClick={() => input.current?.click()}
          className="text-sm text-accent underline underline-offset-4 disabled:no-underline"
        >
          или выберите на диске
        </button>
        <input
          ref={input}
          type="file"
          multiple
          accept={ACCEPT_ATTRIBUTE}
          className="visually-hidden"
          aria-label="Выбрать файлы"
          disabled={disabled}
          onChange={(event) => {
            onAdd(Array.from(event.target.files ?? []));
            // Сбрасываем значение: иначе повторный выбор того же файла не вызовет событие.
            event.target.value = '';
          }}
        />
      </div>

      {files.length > 0 && (
        <ul className="flex flex-col rounded-[var(--radius-md)] border border-border">
          {files.map((picked, index) => (
            <PickedRow
              key={`${picked.file.name}-${index}`}
              picked={picked}
              disabled={disabled}
              onRemove={() => onRemove(index)}
            />
          ))}
        </ul>
      )}
    </div>
  );
};

interface IPickedRowProps {
  picked: PickedFile;
  disabled: boolean;
  onRemove: () => void;
}

const PickedRow = ({ picked, disabled, onRemove }: IPickedRowProps) => {
  const extension = extensionOf(picked.file.name);
  const Icon = ICONS[extension] ?? IconPdf;
  const capability = CAPABILITY[extension];

  return (
    <li className="grid grid-cols-[20px_1fr_auto_auto] items-center gap-[var(--s-4)] border-b border-border px-[var(--s-5)] py-[var(--s-4)] last:border-b-0">
      <Icon width={16} height={16} className="text-muted" />

      <span className="flex min-w-0 flex-col">
        <span className="truncate text-sm">{picked.file.name}</span>
        <span className="mono text-xs text-muted">{formatBytes(picked.file.size)}</span>
      </span>

      {picked.accepted && capability ? (
        <StatusBadge tone={capability.tone} dot={false}>
          {capability.text}
        </StatusBadge>
      ) : (
        <StatusBadge tone="danger" dot={false}>
          Тип не поддерживается
        </StatusBadge>
      )}

      <button
        type="button"
        onClick={onRemove}
        disabled={disabled}
        aria-label={`Убрать ${picked.file.name}`}
        className="grid h-[22px] w-[22px] place-items-center rounded-[var(--radius-xs)] text-muted hover:bg-surface-muted hover:text-text disabled:opacity-40"
      >
        ×
      </button>
    </li>
  );
};

/** Помечает файлы как принимаемые или нет, не отбрасывая их молча. */
export const classifyFiles = (files: readonly File[]): PickedFile[] =>
  files.map((file) => ({ file, accepted: isAccepted(file.name) }));
