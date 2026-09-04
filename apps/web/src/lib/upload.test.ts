import { describe, expect, it } from 'vitest';

import { errorMessage, isKnownError } from './errors';
import { ACCEPTED_EXTENSIONS, ACCEPT_ATTRIBUTE, extensionOf, isAccepted } from './upload';

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
