'use client';

import { useRef, useState, type ChangeEvent, type FC } from 'react';

import { Button } from '@/components/ui';
import { ClearableInput } from '@/components/ui/ClearableInput';
import { cadErrorText } from '@/lib/cad/errors';
import {
  MAX_IMPORT_BYTES,
  MAX_REVIEWER_LENGTH,
  buildRemarksFile,
  importSummary,
  parseRemarksFile,
  remarksFilename,
  toImportBody,
  type IPageSizePt,
  type IRemark,
  type IRemarkBinding,
} from '@/lib/cad/remarks';
import type { CadRemarksFile, CadRemarksImportRead } from '@quantor/api-client';

interface ICadRemarksIoProps {
  binding: IRemarkBinding;
  page: IPageSizePt | null;
  remarks: readonly IRemark[];
  reviewer: string;
  onReviewerChange: (value: string) => void;
  /** Отправка файла на сервер: слияние делает он. */
  onImport: (file: CadRemarksFile) => Promise<CadRemarksImportRead>;
}

type Message = { readonly tone: 'ok' | 'error'; readonly text: string };

/** Скачивание текста файлом через временную ссылку; адрес сразу освобождается. */
const downloadText = (name: string, text: string): void => {
  const url = URL.createObjectURL(new Blob([text], { type: 'application/json;charset=utf-8' }));
  const link = document.createElement('a');
  link.href = url;
  link.download = name;
  document.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
};

/** Проверяющий, экспорт JSON и импорт JSON: файл - способ передать замечания между рабочими местами. */
export const CadRemarksIo: FC<ICadRemarksIoProps> = ({
  binding,
  page,
  remarks,
  reviewer,
  onReviewerChange,
  onImport,
}) => {
  const [message, setMessage] = useState<Message | null>(null);
  const [importing, setImporting] = useState(false);
  const picker = useRef<HTMLInputElement>(null);

  const exportFile = () => {
    if (reviewer.trim() === '') {
      setMessage({ tone: 'error', text: 'Укажите проверяющего: имя нужно для экспорта.' });
      return;
    }
    const now = new Date();
    downloadText(
      remarksFilename(binding, now),
      `${JSON.stringify(buildRemarksFile(binding, reviewer, remarks, now), null, 2)}\n`,
    );
    setMessage({ tone: 'ok', text: `Экспортировано замечаний: ${remarks.length}.` });
  };

  const importFile = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0];
    // Сброс позволяет выбрать тот же файл повторно.
    event.target.value = '';
    if (!file) return;
    if (file.size > MAX_IMPORT_BYTES) {
      setMessage({ tone: 'error', text: 'Файл больше 2 МБ: импорт отклонён.' });
      return;
    }
    let text: string;
    try {
      text = await file.text();
    } catch {
      setMessage({ tone: 'error', text: 'Не удалось прочитать файл.' });
      return;
    }
    const parsed = parseRemarksFile(text, binding, page);
    if (!parsed.ok) {
      setMessage({ tone: 'error', text: `Импорт отклонён. ${parsed.reason}` });
      return;
    }
    // Клиентский разбор - предварительная проверка; привязку и слияние окончательно решает сервер.
    const body = toImportBody(
      buildRemarksFile(binding, parsed.reviewer, parsed.remarks, new Date()),
    );
    setImporting(true);
    try {
      setMessage({ tone: 'ok', text: importSummary(await onImport(body)) });
    } catch (failure) {
      setMessage({ tone: 'error', text: `Импорт отклонён. ${cadErrorText(failure)}` });
    } finally {
      setImporting(false);
    }
  };

  return (
    <div className="flex min-w-0 flex-col gap-[var(--s-4)]">
      <label className="flex min-w-0 flex-col gap-[var(--s-2)]">
        <span className="text-sm">Проверяющий</span>
        <ClearableInput
          label="Проверяющий"
          value={reviewer}
          maxLength={MAX_REVIEWER_LENGTH}
          autoComplete="name"
          onChange={(event) => onReviewerChange(event.target.value)}
          onClear={() => onReviewerChange('')}
          wrapperClassName="w-full"
        />
        <span className="text-micro text-muted">Имя запоминается в этом браузере.</span>
      </label>

      <div className="flex flex-wrap gap-[var(--s-4)]">
        <Button onClick={exportFile} disabled={remarks.length === 0} className="max-md:flex-1">
          Экспорт JSON
        </Button>
        <Button
          onClick={() => picker.current?.click()}
          disabled={importing}
          className="max-md:flex-1"
        >
          Импорт JSON
        </Button>
        <input
          ref={picker}
          type="file"
          accept="application/json,.json"
          aria-label="Файл замечаний для импорта"
          data-testid="remarks-import"
          className="hidden"
          onChange={(event) => void importFile(event)}
        />
      </div>

      {message && (
        <p
          role={message.tone === 'error' ? 'alert' : 'status'}
          className={message.tone === 'error' ? 'text-xs text-danger' : 'text-xs text-muted'}
        >
          {message.text}
        </p>
      )}
    </div>
  );
};
