import { describe, expect, it } from 'vitest';

import {
  DOCUMENTS_FORMS,
  SHEETS_FORMS,
  countOf,
  documentKind,
  formatBytes,
  formatWhen,
  plural,
  projectStatus,
  revisionStatus,
} from './format';

describe('размер файла', () => {
  it('нули и байты показываются без дробной части', () => {
    expect(formatBytes(0)).toBe('0 Б');
    expect(formatBytes(512)).toBe('512 Б');
  });

  it('эталонный архив читается как 47 МБ', () => {
    expect(formatBytes(49_276_811)).toBe('47 МБ');
  });

  it('дробная часть отделяется запятой', () => {
    expect(formatBytes(1_600_000)).toBe('1,5 МБ');
  });
});

describe('склонение', () => {
  it.each([
    [1, 'лист'],
    [2, 'листа'],
    [4, 'листа'],
    [5, 'листов'],
    [11, 'листов'],
    [21, 'лист'],
    [77, 'листов'],
    [383, 'листа'],
  ])('%i → %s', (count, expected) => {
    expect(plural(count, SHEETS_FORMS)).toBe(expected);
  });

  it('число подставляется вместе с формой', () => {
    expect(countOf(3, DOCUMENTS_FORMS)).toBe('3 документа');
  });
});

describe('время изменения', () => {
  const now = new Date('2026-09-04T15:00:00');

  it('сегодняшнее показывается часами', () => {
    expect(formatWhen('2026-09-04T11:42:00', now)).toMatch(/^сегодня, \d{2}:\d{2}$/);
  });

  it('вчерашнее — словом', () => {
    expect(formatWhen('2026-09-03T18:20:00', now)).toMatch(/^вчера, /);
  });

  it('старое — датой без года, если год текущий', () => {
    expect(formatWhen('2026-07-02T10:00:00', now)).not.toMatch(/2026/);
  });

  it('прошлогоднее — датой с годом', () => {
    expect(formatWhen('2025-11-02T10:00:00', now)).toMatch(/2025/);
  });

  it('мусор не роняет интерфейс', () => {
    expect(formatWhen('не дата', now)).toBe('—');
  });
});

describe('состояние проекта', () => {
  const job = (
    status: string,
    progress: number | null = null,
  ): Parameters<typeof projectStatus>[0] => ({
    id: 'job',
    job_type: 'legacy_import',
    status: status as 'queued',
    progress,
    stage: null,
    error_code: null,
    finished_at: null,
  });

  it('без заданий состояния нет', () => {
    // Проект сам по себе не бывает «в процессе импорта» — это состояние задания.
    expect(projectStatus(null)).toBeNull();
  });

  it('выполняющееся задание показывает долю', () => {
    expect(projectStatus(job('running', 0.64))).toEqual({ label: 'Импорт 64 %', tone: 'accent' });
  });

  it('выполняющееся без доли не выдумывает проценты', () => {
    expect(projectStatus(job('running'))?.label).toBe('Импорт');
  });

  it('успешное задание делает проект готовым', () => {
    expect(projectStatus(job('succeeded'))).toEqual({ label: 'Готов', tone: 'success' });
  });

  it('провал виден как ошибка', () => {
    expect(projectStatus(job('failed'))?.tone).toBe('danger');
  });
});

describe('состояния ревизии и типы документов', () => {
  it('нераспознанный PDF подписан честно', () => {
    expect(revisionStatus('unprocessed').label).toBe('Не распознан');
  });

  it('BIM-модель говорит про отсутствие обработчика', () => {
    expect(revisionStatus('processor_unavailable').label).toBe('Обработчик не подключён');
  });

  it('неизвестное состояние отдаётся как есть, а не прячется', () => {
    expect(revisionStatus('нечто').label).toBe('нечто');
  });

  it('типы документов переведены', () => {
    expect(documentKind('recognized_package')).toBe('Распознанный пакет');
    expect(documentKind('navisworks')).toBe('Navisworks');
  });
});
