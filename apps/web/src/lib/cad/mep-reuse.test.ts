import { describe, expect, it } from 'vitest';

import { reusedRouteNotice } from './mep-reuse';

const job = (patch: { job_id?: string; status?: string; attempt?: number } = {}) =>
  ({ job_id: 'j1', status: 'queued', attempt: 0, ...patch }) as Parameters<
    typeof reusedRouteNotice
  >[0];

describe('reusedRouteNotice', () => {
  it('новое задание в очереди без попыток - без сообщения', () => {
    expect(reusedRouteNotice(job(), [])).toBeNull();
    expect(reusedRouteNotice(job(), ['other'])).toBeNull();
  });

  it('задание в очереди, но уже известное панели - прежнее', () => {
    expect(reusedRouteNotice(job(), ['j1'])).toBe(
      'Трассы с этими параметрами уже строятся — открыто текущее задание.',
    );
    expect(reusedRouteNotice(job(), new Set(['j1']))).toContain('уже строятся');
  });

  it('есть попытки - прежнее', () => {
    expect(reusedRouteNotice(job({ attempt: 1 }), [])).toContain('уже строятся');
  });

  it('идёт - сообщение о текущем задании', () => {
    expect(reusedRouteNotice(job({ status: 'running', attempt: 1 }), [])).toContain(
      'уже строятся',
    );
  });

  it('готово - открыт результат, правка через «Пересчитать»', () => {
    const text = reusedRouteNotice(job({ status: 'succeeded' }), []);
    expect(text).toContain('уже построены');
    expect(text).toContain('«Пересчитать»');
  });

  it('ошибка - повтор кнопкой «Повторить»', () => {
    const text = reusedRouteNotice(job({ status: 'failed' }), []);
    expect(text).toContain('завершилось ошибкой');
    expect(text).toContain('«Повторить»');
  });

  it('отменено - новое не создаётся', () => {
    expect(reusedRouteNotice(job({ status: 'cancelled' }), [])).toContain('было отменено');
  });
});
