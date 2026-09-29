/**
 * Коды ошибок API в понятных пользователю формулировках.
 *
 * Сервер отдаёт стабильный код и короткое сообщение. Текст для экрана собирается здесь:
 * так формулировку можно менять, не трогая ни сервер, ни компоненты, а незнакомый код
 * не превращается в пустой экран.
 */

const MESSAGES: Record<string, string> = {
  UNSUPPORTED_FILE_TYPE:
    'Такой тип файла портал не принимает. Подходят ZIP-пакет распознавалки, PDF, а также RVT, NWD, NWC и IFC на хранение.',
  MIME_MISMATCH: 'Содержимое файла не совпадает с расширением. Похоже, файл переименовали.',
  UPLOAD_TOO_LARGE: 'Файл больше допустимого размера.',
  EMPTY_FILE: 'Файл пуст.',
  CORRUPT_ARCHIVE: 'Архив повреждён и не читается.',
  ARCHIVE_UNSAFE_PATH: 'В архиве есть небезопасный файл — импорт остановлен.',
  ARCHIVE_LIMIT_EXCEEDED: 'Архив превышает допустимые пределы по размеру или числу файлов.',
  LEGACY_PDF_MISSING: 'В пакете нет исходного PDF.',
  LEGACY_BLOCKS_INVALID: 'Файл распознанных областей некорректен.',
  LEGACY_SCHEMA_UNSUPPORTED: 'Версия схемы пакета не поддерживается этим портфелем портала.',
  IMPORT_FAILED: 'Импорт не удался. Повторная загрузка запустит его заново.',
  STORAGE_UNAVAILABLE: 'Хранилище файлов недоступно. Проверьте, что оно запущено.',
  DATABASE_UNAVAILABLE: 'База данных недоступна. Проверьте, что она запущена.',
  CONTENT_NOT_AVAILABLE: 'Файл ревизии недоступен в хранилище.',
  NOT_FOUND: 'Объект не найден.',
  VALIDATION_FAILED: 'Данные запроса не приняты.',
  JOB_TRANSITION_INVALID: 'Задание уже завершено — перезапустить его нельзя.',
  NETWORK_ERROR: 'Не удалось связаться с сервером. Проверьте, что бэкенд запущен.',
  FEATURE_DISABLED: 'Эта возможность выключена для пространства.',
  PERMISSION_DENIED: 'Недостаточно прав для этого действия.',

  // Вход и доступ (ADR-0031).
  UNAUTHENTICATED: 'Требуется вход в портал.',
  SESSION_EXPIRED: 'Сеанс завершён. Войдите снова.',
  CSRF_FAILED: 'Запрос не подтверждён. Обновите страницу и повторите.',
  WORKSPACE_FORBIDDEN: 'Вам ещё не назначено рабочее пространство. Обратитесь к администратору.',
  CREDENTIAL_INVALID: 'Неверная почта или пароль.',
  ACCOUNT_PENDING: 'Заявка ещё не одобрена администратором.',
  ACCOUNT_REJECTED: 'Заявка на доступ отклонена. Обратитесь к администратору.',
  ACCOUNT_DISABLED: 'Учётная запись отключена. Обратитесь к администратору.',
  TOO_MANY_ATTEMPTS: 'Слишком много неудачных попыток. Повторите через 15 минут.',
  AUTH_NOT_CONFIGURED: 'Этот способ входа в портале выключен.',

  // Расчётный контур стадии П (ADR-0030).
  CALC_DOCUMENT_NOT_RECOGNIZED:
    'У документа нет распознанного текста: факты собираются только из распознанного пакета.',
  CALC_REVISION_NOT_LATEST: 'У документа есть более новая ревизия — собирайте факты из неё.',

  // TenderHUB. Формулировки разные намеренно: в одном случае чинят ключ, в другом ждут,
  // в третьем идут к администратору — общее «сервис недоступен» не помогает никому.
  TENDERHUB_DISABLED: 'Интеграция с TenderHUB не настроена: на сервере нет ключа доступа.',
  TENDERHUB_AUTH_FAILED:
    'TenderHUB не принял ключ. Нужно выпустить новый в «Настройки → Доступ к API».',
  TENDERHUB_FORBIDDEN:
    'Ключу TenderHUB не выдан доступ к этим данным. Нужен перевыпуск с областью tenders:read.',
  TENDERHUB_RATE_LIMITED: 'TenderHUB ограничил частоту запросов. Подождите минуту и повторите.',
  TENDERHUB_UNAVAILABLE: 'TenderHUB не отвечает. Попробуйте позже.',
  TENDERHUB_TENDER_NOT_FOUND:
    'Тендер не найден в TenderHUB — возможно, он удалён или скрыт от ключа.',
  TENDERHUB_ALREADY_LINKED: 'Проект по этому тендеру уже создан.',
};

export const errorMessage = (code: string, fallback?: string): string =>
  MESSAGES[code] ?? fallback ?? 'Операция не удалась.';

/**
 * Сообщение сервера из отказа. У доменных отказов оно конкретнее общего текста по коду:
 * «Место факта: нужен этаж», а не «Данные запроса не приняты».
 */
export const extractMessage = (error: unknown): string | undefined => {
  const detail = (error as { detail?: { message?: unknown } } | null)?.detail;
  if (typeof detail?.message === 'string') return detail.message;

  const nested = (error as { error?: { detail?: { message?: unknown } } } | null)?.error?.detail;
  if (typeof nested?.message === 'string') return nested.message;

  return undefined;
};

/** Известен ли код порталу. Неизвестный стоит показать как есть — вместе с кодом. */
export const isKnownError = (code: string): boolean => code in MESSAGES;

/**
 * Код ошибки из ответа клиента API.
 *
 * Обёрток две, потому что генерируемый клиент возвращает отказ то как `detail`,
 * то вложенным в `error`. Незнакомая форма считается обрывом связи: это честнее,
 * чем показать пустое сообщение.
 */
export const extractCode = (error: unknown): string => {
  const detail = (error as { detail?: { code?: string } } | null)?.detail;
  if (detail?.code) return detail.code;

  const nested = (error as { error?: { detail?: { code?: string } } } | null)?.error?.detail;
  if (nested?.code) return nested.code;

  return 'NETWORK_ERROR';
};
