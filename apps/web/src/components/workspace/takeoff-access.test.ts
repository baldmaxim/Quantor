import { describe, expect, it } from 'vitest';

import { TAKEOFF_FEATURE, takeoffAccess } from './takeoff-access';

describe('доступ к ручному обмеру', () => {
  it('включён только флагом пилота', () => {
    expect(takeoffAccess({ [TAKEOFF_FEATURE]: true })).toEqual({ enabled: true, hint: undefined });
  });

  it('выключенный флаг закрывает обмер и объясняет почему', () => {
    const access = takeoffAccess({ [TAKEOFF_FEATURE]: false });

    expect(access.enabled).toBe(false);
    expect(access.hint).toMatch(/пилот/);
  });

  it('пока флагов нет, обмер закрыт, а не открыт', () => {
    // `meta` ещё не пришла или упала: показать инструменты значило бы пообещать то, на что
    // сервер ответит отказом.
    expect(takeoffAccess({}).enabled).toBe(false);
  });

  it('чужие флаги обмер не открывают', () => {
    expect(takeoffAccess({ 'takeoff.ai': true, viewer: true }).enabled).toBe(false);
  });
});
