'use client';

import { env } from './env';

/**
 * Загрузка файла с настоящим ходом выполнения.
 *
 * Здесь XMLHttpRequest, а не fetch, ровно по одной причине: fetch не сообщает о ходе
 * отправки тела. Для архива на 50 МБ это принципиально — без полосы пользователь не
 * отличает медленную загрузку от зависшей и жмёт кнопку второй раз.
 *
 * Файл не читается в память: XHR отправляет его потоком из FormData.
 */

export interface UploadProgress {
  /** Доля отправленного от 0 до 1. null — браузер не сообщает общий размер. */
  readonly fraction: number | null;
  readonly loadedBytes: number;
  readonly totalBytes: number | null;
}

export interface UploadResult {
  readonly document: { id: string; display_name: string; document_kind: string };
  readonly revision: { id: string; processing_status: string; source_size: number };
  readonly job: { id: string; status: string } | null;
  readonly is_duplicate: boolean;
}

export class UploadError extends Error {
  constructor(
    /** Стабильный код от сервера. Интерфейс опирается на него, а не на текст. */
    readonly code: string,
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = 'UploadError';
  }
}

interface UploadOptions {
  readonly projectId: string;
  readonly file: File;
  /** Добавить как новую ревизию существующего документа. */
  readonly documentId?: string;
  readonly onProgress?: (progress: UploadProgress) => void;
  readonly signal?: AbortSignal;
}

const NETWORK_ERROR = 'NETWORK_ERROR';

export const uploadFile = ({
  projectId,
  file,
  documentId,
  onProgress,
  signal,
}: UploadOptions): Promise<UploadResult> =>
  new Promise((resolve, reject) => {
    const form = new FormData();
    form.append('file', file, file.name);
    if (documentId) form.append('document_id', documentId);

    const request = new XMLHttpRequest();
    request.open('POST', `${env.apiBaseUrl}/api/v1/projects/${projectId}/uploads`);
    request.responseType = 'json';

    request.upload.addEventListener('progress', (event) => {
      onProgress?.({
        fraction: event.lengthComputable ? event.loaded / event.total : null,
        loadedBytes: event.loaded,
        totalBytes: event.lengthComputable ? event.total : null,
      });
    });

    request.addEventListener('load', () => {
      const payload: unknown = request.response;

      if (request.status >= 200 && request.status < 300) {
        resolve(payload as UploadResult);
        return;
      }
      reject(toUploadError(payload, request.status));
    });

    request.addEventListener('error', () => {
      reject(new UploadError(NETWORK_ERROR, 'Не удалось связаться с сервером', 0));
    });

    request.addEventListener('abort', () => {
      reject(new DOMException('Загрузка отменена', 'AbortError'));
    });

    signal?.addEventListener('abort', () => request.abort(), { once: true });

    request.send(form);
  });

/** Достаёт безопасный код ошибки из ответа API. */
const toUploadError = (payload: unknown, status: number): UploadError => {
  const detail = (payload as { detail?: { code?: string; message?: string } } | null)?.detail;

  if (detail?.code) {
    return new UploadError(detail.code, detail.message ?? 'Загрузка не удалась', status);
  }
  // Ошибка проверки от FastAPI приходит другой формой — сводим её к тому же виду.
  return new UploadError('VALIDATION_FAILED', 'Файл не принят сервером', status);
};

/** Расширения, которые портал принимает. Список дублирует серверный и сверяется тестом. */
export const ACCEPTED_EXTENSIONS = ['zip', 'pdf', 'rvt', 'nwd', 'nwc', 'ifc'] as const;

export const ACCEPT_ATTRIBUTE = ACCEPTED_EXTENSIONS.map((ext) => `.${ext}`).join(',');

export const extensionOf = (filename: string): string => {
  const tail = filename.split('.').pop();
  return tail && tail !== filename ? tail.toLowerCase() : '';
};

export const isAccepted = (filename: string): boolean =>
  (ACCEPTED_EXTENSIONS as readonly string[]).includes(extensionOf(filename));
