import { afterEach, describe, expect, it, vi } from 'vitest';

import { errorMessage, isKnownError } from './errors';
import {
  ACCEPTED_EXTENSIONS,
  ACCEPT_ATTRIBUTE,
  extensionOf,
  isAccepted,
  uploadFile,
} from './upload';

/**
 * Приём файлов на стороне интерфейса.
 *
 * Список принимаемых расширений дублирует серверный намеренно: браузер должен отказать
 * до отправки пятидесяти мегабайт. Но раз список дублирован, он обязан совпадать —
 * это и проверяется.
 */

// Значения из apps/api/app/services/uploads.py. Расхождение означает, что интерфейс
// обещает или запрещает не то, что делает сервер.
const SERVER_EXTENSIONS = ['zip', 'pdf', 'rvt', 'nwd', 'nwc', 'ifc'];

describe('принимаемые типы', () => {
  it('совпадают с серверным списком', () => {
    expect([...ACCEPTED_EXTENSIONS].sort()).toEqual([...SERVER_EXTENSIONS].sort());
  });

  it('атрибут accept собирается из того же списка', () => {
    expect(ACCEPT_ATTRIBUTE).toBe('.zip,.pdf,.rvt,.nwd,.nwc,.ifc');
  });

  it.each(['пакет.zip', 'ЧЕРТЁЖ.PDF', 'модель.rvt', 'сводная.NWD'])('%s принимается', (name) => {
    expect(isAccepted(name)).toBe(true);
  });

  it.each(['скрипт.exe', 'архив.rar', 'смета.xlsx', 'без_расширения', 'план.dwg'])(
    '%s отклоняется',
    (name) => {
      expect(isAccepted(name)).toBe(false);
    },
  );

  it('точка в имени не путает разбор', () => {
    expect(extensionOf('01-03-00-01-12_ПД-00260560-АР.v2.pdf')).toBe('pdf');
    expect(extensionOf('.gitignore')).toBe('gitignore');
    expect(extensionOf('файл')).toBe('');
  });
});

describe('сообщения об ошибках', () => {
  it.each([
    'UNSUPPORTED_FILE_TYPE',
    'MIME_MISMATCH',
    'UPLOAD_TOO_LARGE',
    'EMPTY_FILE',
    'CORRUPT_ARCHIVE',
    'ARCHIVE_UNSAFE_PATH',
    'ARCHIVE_LIMIT_EXCEEDED',
    'LEGACY_PDF_MISSING',
    'LEGACY_BLOCKS_INVALID',
    'LEGACY_SCHEMA_UNSUPPORTED',
    'IMPORT_FAILED',
    'STORAGE_UNAVAILABLE',
    'DATABASE_UNAVAILABLE',
  ])('код %s переведён на русский', (code) => {
    expect(isKnownError(code)).toBe(true);
    expect(errorMessage(code)).toMatch(/[а-яё]/i);
  });

  it('незнакомый код не оставляет пользователя с пустым экраном', () => {
    expect(errorMessage('НЕЧТО_НЕВЕДОМОЕ')).toBeTruthy();
  });

  it('запасной текст используется, когда код неизвестен', () => {
    expect(errorMessage('НЕЧТО', 'Своё сообщение')).toBe('Своё сообщение');
  });

  it('сообщения не содержат технических подробностей', () => {
    // Наружу не должны попадать ни трассировки, ни строки подключения.
    for (const code of ['STORAGE_UNAVAILABLE', 'DATABASE_UNAVAILABLE', 'IMPORT_FAILED']) {
      const text = errorMessage(code);
      expect(text).not.toMatch(/Traceback|postgresql:\/\/|asyncpg|127\.0\.0\.1/);
    }
  });
});

describe('запрос загрузки', () => {
  /** Подменный XHR: запоминает, с чем запрос ушёл, и сразу отвечает успехом. */
  class FakeXhr {
    static last: FakeXhr | null = null;
    withCredentials = false;
    responseType = '';
    status = 0;
    response: unknown = null;
    readonly headers: Record<string, string> = {};
    readonly upload = { addEventListener: () => undefined };
    private readonly listeners: Record<string, () => void> = {};

    constructor() {
      FakeXhr.last = this;
    }

    open() {}

    setRequestHeader(name: string, value: string) {
      this.headers[name] = value;
    }

    addEventListener(type: string, listener: () => void) {
      this.listeners[type] = listener;
    }

    send() {
      this.status = 201;
      this.response = { document: {}, revision: {}, job: null, is_duplicate: false };
      this.listeners.load?.();
    }

    abort() {}
  }

  afterEach(() => {
    vi.unstubAllGlobals();
    document.cookie = 'quantor_csrf=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/';
  });

  it('несёт cookie сеанса и подтверждение CSRF', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXhr);
    document.cookie = 'quantor_csrf=token-123; path=/';

    await uploadFile({ projectId: 'p1', file: new File(['x'], 'план.pdf') });

    expect(FakeXhr.last?.withCredentials).toBe(true);
    expect(FakeXhr.last?.headers['X-CSRF-Token']).toBe('token-123');
  });

  it('без cookie подтверждения пустой заголовок не отправляется', async () => {
    vi.stubGlobal('XMLHttpRequest', FakeXhr);

    await uploadFile({ projectId: 'p1', file: new File(['x'], 'план.pdf') });

    expect(FakeXhr.last?.headers).not.toHaveProperty('X-CSRF-Token');
  });
});
