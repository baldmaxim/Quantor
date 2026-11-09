import type { CadEventRead, CadEventsRead } from '@quantor/api-client';

/**
 * Накопленный журнал событий одной попытки задания.
 *
 * Сервер отдаёт события по порядку номеров после курсора `after_seq`. Журнал хранит всё, что
 * уже получено, и принимает только следующие по номеру события: повторный, запоздавший или
 * чужой ответ его не портит.
 */
export interface ICadEventLog {
  readonly jobId: string;
  readonly attempt: number;
  /** События строго по возрастанию `seq`, без повторов. */
  readonly events: readonly CadEventRead[];
  /** Номер последнего принятого события; следующий запрос идёт с `after_seq` = этому значению. */
  readonly lastSeq: number;
  /** Последний номер, о котором сообщил сервер. Больше `lastSeq` — часть событий ещё не получена. */
  readonly serverLastSeq: number;
}

export const emptyEventLog = (jobId: string, attempt: number): ICadEventLog => ({
  jobId,
  attempt,
  events: [],
  lastSeq: 0,
  serverLastSeq: 0,
});

/** Все события, о которых сообщил сервер, получены. */
export const isEventLogComplete = (log: ICadEventLog): boolean => log.lastSeq >= log.serverLastSeq;

/**
 * Добавляет к журналу ответ сервера.
 *
 * Ответ другого задания или другой попытки игнорируется. Принимаются только события с
 * номером больше последнего известного, по возрастанию. Курсор двигается по принятым
 * событиям, а не по `last_seq` ответа: при обрезке по `limit` иначе пропали бы события.
 */
export const mergeEvents = (log: ICadEventLog, incoming: CadEventsRead): ICadEventLog => {
  if (incoming.job_id !== log.jobId || incoming.attempt !== log.attempt) {
    return log;
  }

  const fresh: CadEventRead[] = [];
  let cursor = log.lastSeq;
  for (const event of [...incoming.events].sort((a, b) => a.seq - b.seq)) {
    if (event.seq > cursor && event.attempt === log.attempt) {
      fresh.push(event);
      cursor = event.seq;
    }
  }

  const serverLastSeq = Math.max(log.serverLastSeq, incoming.last_seq, cursor);
  if (fresh.length === 0 && serverLastSeq === log.serverLastSeq) {
    return log;
  }
  return {
    ...log,
    events: fresh.length === 0 ? log.events : [...log.events, ...fresh],
    lastSeq: cursor,
    serverLastSeq,
  };
};

/** События документа целиком (без событий отдельных видов). */
export const documentEvents = (log: ICadEventLog): readonly CadEventRead[] =>
  log.events.filter((event) => event.scope === 'document');
