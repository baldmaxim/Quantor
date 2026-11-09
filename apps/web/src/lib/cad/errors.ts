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
