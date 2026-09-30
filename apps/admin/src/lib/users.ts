import type { AdminUserRead, ApprovalStatus } from '@quantor/api-client';
import type { BadgeTone } from '@quantor/ui';

/**
 * Подписи ролей и состояний пользователя.
 *
 * Одно место на весь раздел: иначе таблица и диалог назовут одну роль по-разному.
 */

export const ROLE_LABELS: Record<string, string> = {
  workspace_admin: 'Администратор пространства',
  engineer: 'Инженер',
  reviewer: 'Проверяющий',
  viewer: 'Читатель',
  platform_admin: 'Администратор платформы',
  service: 'Служебная',
};

export const roleLabel = (role: string): string => ROLE_LABELS[role] ?? role;

const APPROVAL: Record<ApprovalStatus, { label: string; tone: BadgeTone }> = {
  pending: { label: 'ждёт решения', tone: 'warning' },
  approved: { label: 'одобрен', tone: 'success' },
  rejected: { label: 'отклонён', tone: 'danger' },
};

/** Состояние для отметки: отключение важнее одобрения — войти всё равно нельзя. */
export const userState = (user: AdminUserRead): { label: string; tone: BadgeTone } => {
  if (!user.is_active) return { label: 'отключён', tone: 'neutral' };
  return APPROVAL[user.approval_status];
};

/** Заблокирован ли вход перебором прямо сейчас. */
export const isLocked = (user: AdminUserRead, now: Date = new Date()): boolean =>
  user.locked_until !== null &&
  user.locked_until !== undefined &&
  new Date(user.locked_until) > now;

/** Сообщение сервера из отказа: оно конкретнее общего «не удалось». */
export const failureText = (error: unknown): string => {
  const detail = (error as { detail?: { message?: unknown } } | null)?.detail;
  if (typeof detail?.message === 'string') return detail.message;
  return 'Сервер отклонил действие. Обновите страницу и повторите.';
};

/**
 * «1 заявка ждёт решения», «3 заявки ждут решения», «11 заявок ждут решения».
 * Русское согласование: форма слова и глагола зависит от последних цифр числа.
 */
export const pendingSummary = (count: number): string => {
  if (count <= 0) return 'Новых заявок нет';
  const mod10 = count % 10;
  const mod100 = count % 100;
  if (mod10 === 1 && mod100 !== 11) return `${count} заявка ждёт решения`;
  if (mod10 >= 2 && mod10 <= 4 && (mod100 < 12 || mod100 > 14)) {
    return `${count} заявки ждут решения`;
  }
  return `${count} заявок ждут решения`;
};

/** Ссылка на форму заявки в портале — её администратор отправляет коллегам. */
export const registrationUrl = (portalUrl: string): string =>
  new URL('/register', portalUrl).toString();
