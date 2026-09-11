/**
 * Доступ к ручному обмеру в рабочей области.
 *
 * Ручной обмер — пилотная возможность (ADR-0023): сделана, но включается администратором на
 * пространство. Решает флаг из `/api/v1/meta`, а не этот файл, — сервер закрывает маршруты
 * обмера тем же флагом, и вкладка, открытая при выключенном флаге, упиралась бы в отказ.
 */

export const TAKEOFF_FEATURE = 'takeoff.manual';

export interface ITakeoffAccess {
  readonly enabled: boolean;
  /** Почему выключено. Показывается в подсказке вкладки и инструментов. */
  readonly hint: string | undefined;
}

const DISABLED_HINT = 'Этап 2A · пилот — включается администратором для пространства';

export const takeoffAccess = (features: Readonly<Record<string, boolean>>): ITakeoffAccess =>
  // Строгое сравнение: пока `meta` не пришла, флага нет, и это «выключено», а не «включено».
  features[TAKEOFF_FEATURE] === true
    ? { enabled: true, hint: undefined }
    : { enabled: false, hint: DISABLED_HINT };
