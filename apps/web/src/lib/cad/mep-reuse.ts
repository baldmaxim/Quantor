import type { CadJobRead } from '@quantor/api-client';

/**
 * Сервер идемпотентен: «Построить трассы» с теми же одобрением, параметрами, генератором,
 * реестром стояков и уровнями возвращает существующее задание тем же 202. Задание считается
 * прежним, если оно уже не в очереди, имеет попытки или его id панель знала до нажатия.
 */
export const reusedRouteNotice = (
  job: Pick<CadJobRead, 'job_id' | 'status' | 'attempt'>,
  knownIds: readonly string[] | ReadonlySet<string>,
): string | null => {
  const known = Array.isArray(knownIds)
    ? knownIds.includes(job.job_id)
    : (knownIds as ReadonlySet<string>).has(job.job_id);
  if (job.status === 'queued' && !(job.attempt > 0) && !known) return null;
  switch (job.status) {
    case 'succeeded':
      return 'Трассы с этими параметрами уже построены — открыт готовый результат. Изменить отметку и высоту — «Пересчитать».';
    case 'failed':
      return 'Построение с этими параметрами уже завершилось ошибкой — открыто это задание. Новое с теми же параметрами не создаётся: повторите его кнопкой «Повторить», если она доступна.';
    case 'cancelled':
      return 'Задание с этими параметрами было отменено — новое с теми же параметрами не создаётся.';
    default:
      return 'Трассы с этими параметрами уже строятся — открыто текущее задание.';
  }
};
