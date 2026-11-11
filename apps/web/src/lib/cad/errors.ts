import { errorMessage, extractCode, extractMessage } from '@/lib/errors';

import { calibrationPagesOf, calibrationRequiredText } from './sheets';

/** Тексты кодов CAD-контура; остальные коды — из общего словаря портала. */
const CAD_MESSAGES: Readonly<Record<string, string>> = {
  JOB_NOT_RETRYABLE: 'Этот отказ повтором не чинится.',
  CAD_INPUT_INVALID: 'PDF не подходит для преобразования в CAD.',
  CAD_PARAMS_INVALID: 'Параметры преобразования вне контракта: проверьте выбор страниц.',
  CAD_INPUT_LIMIT_EXCEEDED: 'PDF превышает пределы преобразования: выберите меньше страниц.',
  CAD_CALIBRATION_REQUIRED: calibrationRequiredText([]),
  CAD_ENGINE_FAILED: 'Движок CAD не выдал проверенный результат.',
  CAD_ENGINE_UNAVAILABLE: 'Движок CAD не установлен или не прошёл проверку.',
  CAD_RESULT_NOT_READY: 'Результат преобразования ещё не готов.',
  CAD_OPEN_REMARKS: 'Есть открытые замечания: закройте их или отметьте проверенными.',
  CAD_ALREADY_DECIDED: 'Решение по этому виду уже принято.',
  CAD_VIEW_NOT_APPROVED: 'Вид не одобрен: сначала одобрите его.',
  CAD_ROUTES_NOT_ACCEPTED: 'Трассы не приняты: 3D DXF доступен после принятия.',
  CAD_MEP_NOT_BUILT: 'Трассы для этого вида не построены: генератор не нашёл решения.',
  CAD_ALREADY_REVOKED: 'Это решение уже отозвано.',
  CAD_ROUTES_ACCEPTED: 'По этому одобрению приняты трассы: сначала отзовите принятие.',
  CAD_VIEW_APPROVAL_REVOKED: 'Одобрение вида отозвано: одобрите вид заново.',
  CAD_ELEVATION_NOT_FOUND:
    'Отметка пола не найдена в документации: задайте отметку и высоту вручную.',
  CAD_FLOOR_HEIGHT_NOT_FOUND:
    'Высота этажа не определена по документации: задайте отметку и высоту вручную.',
  CAD_WALLS_NOT_READY: 'Конструкции вида ещё не посчитаны.',
  CAD_WALLS_BUSY: 'Конструкции этого вида уже считаются.',
  CAD_RECOMPUTE_SAME_PARAMS: 'Те же отметка, высота и версия генератора: результат не изменится.',
};

/** Текст отказа API для показа: код CAD, затем общий словарь, затем сообщение сервера. */
export const cadErrorText = (error: unknown): string => {
  const code = extractCode(error);
  if (code === 'CAD_CALIBRATION_REQUIRED') {
    return calibrationRequiredText(calibrationPagesOf(error));
  }
  return CAD_MESSAGES[code] ?? errorMessage(code, extractMessage(error));
};

/** Текст по готовому коду (например, `error_code` попытки). */
export const cadCodeText = (code: string): string => CAD_MESSAGES[code] ?? errorMessage(code);
