import { describe, expect, it } from 'vitest';

import { constructionsRead } from './constructions-fixtures';
import { isWallsActive, latestWallsFailure, latestWallsStatus, wallsJobStatus } from './constructions-queries';

describe('статус расчёта из отказа 404', () => {
  it('читает detail.issue.job_status в обеих формах ответа клиента', () => {
    expect(wallsJobStatus({ detail: { code: 'CAD_WALLS_NOT_READY', issue: { job_status: 'running' } } })).toBe(
      'running',
    );
    expect(
      wallsJobStatus({ error: { detail: { issue: { job_status: 'failed' } } } }),
    ).toBe('failed');
    expect(wallsJobStatus({ detail: { code: 'CAD_WALLS_NOT_READY' } })).toBeNull();
    expect(wallsJobStatus(null)).toBeNull();
  });

  it('очередь и выполнение - расчёт идёт', () => {
    expect(isWallsActive('queued')).toBe(true);
    expect(isWallsActive('running')).toBe(true);
    expect(isWallsActive('failed')).toBe(false);
    expect(isWallsActive(null)).toBe(false);
  });
});

describe('свежее задание пересчёта в ответе', () => {
  const latest = (status: 'queued' | 'running' | 'succeeded' | 'failed', extra = {}) =>
    constructionsRead({
      latest_walls_job: {
        id: 'w2',
        status,
        error_code: null,
        error_message: null,
        created_at: '2026-11-11T10:00:00Z',
        ...extra,
      },
    });

  it('статус берётся из latest_walls_job; без него - null', () => {
    expect(latestWallsStatus(latest('running'))).toBe('running');
    expect(latestWallsStatus(constructionsRead())).toBeNull();
    expect(latestWallsStatus(undefined)).toBeNull();
  });

  it('текст отказа - только у упавшего задания: сообщение, иначе текст по коду', () => {
    expect(latestWallsFailure(latest('failed', { error_message: 'скрипт упал' }))).toBe('скрипт упал');
    expect(latestWallsFailure(latest('failed', { error_code: 'CAD_ENGINE_FAILED' }))).toBeTruthy();
    expect(latestWallsFailure(latest('failed'))).toBe('причина не указана');
    expect(latestWallsFailure(latest('running'))).toBeNull();
    expect(latestWallsFailure(latest('succeeded'))).toBeNull();
    expect(latestWallsFailure(null)).toBeNull();
  });
});
