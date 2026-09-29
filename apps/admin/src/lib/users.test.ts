import type { AdminUserRead } from '@quantor/api-client';
import { describe, expect, it } from 'vitest';

import { isLocked, roleLabel, userState } from './users';

const user = (patch: Partial<AdminUserRead> = {}): AdminUserRead => ({
  id: 'u1',
  email: 'engineer@example.ru',
  display_name: 'Инженер',
  is_local: true,
  approval_status: 'approved',
  is_active: true,
  is_platform_admin: false,
  must_change_password: false,
  locked_until: null,
  last_login_at: null,
  created_at: '2026-09-29T00:00:00Z',
  memberships: [],
  ...patch,
});

describe('состояние пользователя', () => {
  it('заявка ждёт решения', () => {
    expect(userState(user({ approval_status: 'pending' }))).toEqual({
      label: 'ждёт решения',
      tone: 'warning',
    });
  });

  it('отключение важнее одобрения', () => {
    expect(userState(user({ is_active: false })).label).toBe('отключён');
  });

  it('блокировка перебором видна только пока действует', () => {
    const now = new Date('2026-09-29T12:00:00Z');
    expect(isLocked(user({ locked_until: '2026-09-29T12:10:00Z' }), now)).toBe(true);
    expect(isLocked(user({ locked_until: '2026-09-29T11:50:00Z' }), now)).toBe(false);
    expect(isLocked(user(), now)).toBe(false);
  });

  it('роль подписана по-русски', () => {
    expect(roleLabel('engineer')).toBe('Инженер');
    expect(roleLabel('неизвестная')).toBe('неизвестная');
  });
});
