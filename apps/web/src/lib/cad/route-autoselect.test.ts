import { describe, expect, it } from 'vitest';

import { pickAutoRoute } from './route-autoselect';

type Job = Parameters<typeof pickAutoRoute>[0][number];

const PARENT = 'parent-1';

const route = (id: string, over: Partial<Job> = {}): Job => ({
  job_id: id,
  job_type: 'cad_mep_route',
  parent_job_id: PARENT,
  page_index: 0,
  view: 1,
  status: 'succeeded',
  created_at: '2026-11-10T10:00:00Z',
  ...over,
});

const scope = { parentJobId: PARENT, pageIndex: 0, view: 1 };

describe('pickAutoRoute', () => {
  it('нет route-заданий - null', () => {
    expect(pickAutoRoute([], scope)).toBeNull();
    expect(pickAutoRoute([route('c', { job_type: 'cad_pdf_convert' })], scope)).toBeNull();
  });

  it('берёт самое новое успешное задание листа, порядок списка не важен', () => {
    const jobs = [
      route('old', { created_at: '2026-11-10T09:00:00Z' }),
      route('new', { created_at: '2026-11-10T11:00:00Z' }),
      route('mid', { created_at: '2026-11-10T10:00:00Z' }),
    ];
    expect(pickAutoRoute(jobs, scope)?.job_id).toBe('new');
  });

  it('успешное важнее более нового, но не завершённого', () => {
    const jobs = [
      route('running', { status: 'running', created_at: '2026-11-10T12:00:00Z' }),
      route('ok', { created_at: '2026-11-10T10:00:00Z' }),
    ];
    expect(pickAutoRoute(jobs, scope)?.job_id).toBe('ok');
  });

  it('успешных нет - самое новое вообще, чтобы был виден ход', () => {
    const jobs = [
      route('failed', { status: 'failed', created_at: '2026-11-10T09:00:00Z' }),
      route('running', { status: 'running', created_at: '2026-11-10T12:00:00Z' }),
    ];
    expect(pickAutoRoute(jobs, scope)?.job_id).toBe('running');
  });

  it('смена листа: берутся только трассы нового листа', () => {
    const jobs = [route('p0'), route('p3', { page_index: 3 })];
    expect(pickAutoRoute(jobs, { ...scope, pageIndex: 3 })?.job_id).toBe('p3');
    expect(pickAutoRoute(jobs, { ...scope, pageIndex: 5 })).toBeNull();
  });

  it('чужой родитель или вид не подходят', () => {
    const jobs = [route('a', { parent_job_id: 'other' }), route('b', { view: 2 })];
    expect(pickAutoRoute(jobs, scope)).toBeNull();
    expect(pickAutoRoute(jobs, { ...scope, view: 2 })?.job_id).toBe('b');
  });

  it('вид листа не известен - null', () => {
    const jobs = [route('a')];
    expect(pickAutoRoute(jobs, { ...scope, parentJobId: null })).toBeNull();
    expect(pickAutoRoute(jobs, { ...scope, pageIndex: null })).toBeNull();
    expect(pickAutoRoute(jobs, { ...scope, view: null })).toBeNull();
  });

  it('новое завершённое задание подхватывается', () => {
    const before = [route('old', { created_at: '2026-11-10T09:00:00Z' }), route('next', { status: 'running', created_at: '2026-11-10T11:00:00Z' })];
    expect(pickAutoRoute(before, scope)?.job_id).toBe('old');
    const after = before.map((job) => (job.job_id === 'next' ? { ...job, status: 'succeeded' as const } : job));
    expect(pickAutoRoute(after, scope)?.job_id).toBe('next');
  });
});
