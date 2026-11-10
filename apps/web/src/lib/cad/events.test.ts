import type { CadEventRead, CadEventsRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import {
  documentEvents,
  emptyEventLog,
  eventDisplayStatuses,
  isEventLogComplete,
  mergeEvents,
} from './events';

const JOB = '11111111-1111-4111-8111-111111111111';

const event = (seq: number, overrides: Partial<CadEventRead> = {}): CadEventRead => ({
  at: '2026-11-09T10:00:00Z',
  attempt: 1,
  scope: 'document',
  seq,
  status: 'running',
  phase: 'worker',
  ...overrides,
});

const response = (
  events: CadEventRead[],
  lastSeq: number,
  overrides: Partial<CadEventsRead> = {},
): CadEventsRead => ({
  job_id: JOB,
  attempt: 1,
  events,
  last_seq: lastSeq,
  finished: false,
  ...overrides,
});

describe('mergeEvents', () => {
  it('добавляет события по порядку и двигает курсор', () => {
    const log = mergeEvents(emptyEventLog(JOB, 1), response([event(1), event(2)], 2));
    expect(log.events.map((item) => item.seq)).toEqual([1, 2]);
    expect(log.lastSeq).toBe(2);
    expect(isEventLogComplete(log)).toBe(true);
  });

  it('принимает только события новее курсора и не дублирует повторы', () => {
    const first = mergeEvents(emptyEventLog(JOB, 1), response([event(1), event(2)], 2));
    const next = mergeEvents(first, response([event(2), event(3)], 3));
    expect(next.events.map((item) => item.seq)).toEqual([1, 2, 3]);
    expect(next.lastSeq).toBe(3);
  });

  it('игнорирует запоздавший ответ со старыми номерами', () => {
    const first = mergeEvents(emptyEventLog(JOB, 1), response([event(1), event(2), event(3)], 3));
    const stale = mergeEvents(first, response([event(1), event(2)], 2));
    expect(stale).toBe(first);
  });

  it('упорядочивает события внутри ответа', () => {
    const log = mergeEvents(emptyEventLog(JOB, 1), response([event(3), event(1), event(2)], 3));
    expect(log.events.map((item) => item.seq)).toEqual([1, 2, 3]);
  });

  it('игнорирует ответ другого задания или другой попытки', () => {
    const base = emptyEventLog(JOB, 1);
    expect(mergeEvents(base, response([event(1)], 1, { job_id: 'other' }))).toBe(base);
    expect(mergeEvents(base, response([event(1, { attempt: 2 })], 1, { attempt: 2 }))).toBe(base);
  });

  it('не выдаёт журнал за полный, если сервер знает больше событий (обрезка по limit)', () => {
    const log = mergeEvents(emptyEventLog(JOB, 1), response([event(1), event(2)], 5));
    expect(log.lastSeq).toBe(2);
    expect(log.serverLastSeq).toBe(5);
    expect(isEventLogComplete(log)).toBe(false);
    const done = mergeEvents(log, response([event(3), event(4), event(5)], 5));
    expect(isEventLogComplete(done)).toBe(true);
  });

  it('допускает пропуски в номерах (сервер отбросил часть событий)', () => {
    const log = mergeEvents(emptyEventLog(JOB, 1), response([event(1), event(7)], 7));
    expect(log.events.map((item) => item.seq)).toEqual([1, 7]);
    expect(isEventLogComplete(log)).toBe(true);
  });

  it('отделяет события документа от событий видов', () => {
    const log = mergeEvents(
      emptyEventLog(JOB, 1),
      response([event(1), event(2, { scope: 'view', view: 1, page_index: 0 })], 2),
    );
    expect(documentEvents(log).map((item) => item.seq)).toEqual([1]);
  });
});

describe('статус строки события', () => {
  const phases = ['claimed', 'download', 'verify', 'worker', 'publish'];
  const started = (): CadEventRead[] =>
    phases.map((phase, index) => event(index + 1, { phase, status: 'running' }));

  it('начатые этапы с продолжением показываются выполненными, последний - по исходу', () => {
    expect(eventDisplayStatuses(started(), 'running')).toEqual([
      'done',
      'done',
      'done',
      'done',
      'running',
    ]);
    expect(eventDisplayStatuses(started(), 'succeeded')).toEqual(Array(5).fill('done'));
  });

  it('последний этап оборванной попытки - ошибка, не «выполнено»', () => {
    expect(eventDisplayStatuses(started(), 'failed').at(-1)).toBe('error');
    expect(eventDisplayStatuses(started(), 'lost').at(-1)).toBe('error');
  });

  it('итоговые статусы не перекрашиваются', () => {
    const events = [
      event(1, { phase: 'worker', status: 'running' }),
      event(2, { phase: 'published', status: 'done' }),
      event(3, { phase: 'failed', status: 'failed' }),
      event(4, { phase: 'failed', status: 'error' }),
    ];
    expect(eventDisplayStatuses(events, 'failed')).toEqual(['done', 'done', 'failed', 'error']);
  });

  it('повторные события одного этапа закрываются вместе с ним', () => {
    const events = [
      event(1, { phase: 'worker' }),
      event(2, { phase: 'worker' }),
      event(3, { phase: 'collect' }),
    ];
    expect(eventDisplayStatuses(events, 'running')).toEqual(['done', 'done', 'running']);
  });

  it('события видов показываются со своим статусом и не закрывают этапы документа', () => {
    const events = [
      event(1, { phase: 'worker', status: 'running' }),
      event(2, { scope: 'view', stage: 'regions', status: 'needs_review', page_index: 0, view: 1 }),
      event(3, { scope: 'view', stage: 'scale', status: 'running', page_index: 0, view: 1 }),
    ];
    expect(eventDisplayStatuses(events, 'running')).toEqual(['running', 'needs_review', 'running']);
  });
});
