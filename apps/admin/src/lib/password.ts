/**
 * Временный пароль, который администратор выдаёт пользователю.
 *
 * Генерируется в браузере криптографическим генератором и уходит на сервер один раз —
 * в журнал попадает только факт выдачи. Без похожих символов (0/O, 1/l/I): пароль
 * диктуют голосом и переписывают с экрана.
 */

const ALPHABET = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789';

export const TEMPORARY_PASSWORD_LENGTH = 14;

export const generatePassword = (length: number = TEMPORARY_PASSWORD_LENGTH): string => {
  const values = new Uint32Array(length);
  crypto.getRandomValues(values);
  return Array.from(values, (value) => ALPHABET[value % ALPHABET.length]).join('');
};
