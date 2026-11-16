import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import { Camera } from '@/lib/viewer/camera';

type MutateOptions<T> = { onSuccess?: (value: T) => void };

const mocks = vi.hoisted(() => ({
  jobArgs: vi.fn(),
  createMutate: vi.fn(),
  createReset: vi.fn(),
  acceptMutate: vi.fn(),
  acceptReset: vi.fn(),
  jobData: { current: undefined as unknown },
  acceptPending: { current: false },
}));

vi.mock('@/lib/cad/style-profile-queries', () => ({
  useStyleProfile: () => ({ data: { current: { version: 2 } }, isError: false, error: null, refetch: vi.fn() }),
  useCreateStylePreview: () => ({
    mutate: mocks.createMutate,
    reset: mocks.createReset,
    isPending: false,
    isError: false,
    error: null,
  }),
  useStylePreviewJob: (...args: unknown[]) => {
    mocks.jobArgs(...args);
    return { data: mocks.jobData.current, isError: false, error: null };
  },
  useAcceptStylePreview: () => ({
    mutate: mocks.acceptMutate,
    reset: mocks.acceptReset,
    isPending: mocks.acceptPending.current,
    isError: false,
    error: null,
  }),
}));

import { useWorkspaceCadStyle } from './useWorkspaceCadStyle';

const camera = new Camera();

const base = {
  projectId: 'p1',
  documentId: 'd1',
  revisionId: 'r1',
  pageIndex: 0 as number | null,
  pageSize: { width: 100, height: 100 },
  camera,
  load: true,
  active: true,
  blocked: false,
};

const finished = {
  job_id: 'job1',
  status: 'succeeded',
  error_code: null,
  error_message: null,
  result: {
    result_status: 'profile',
    base_version: 5,
    preview: {},
    profile: {},
    reasons: [],
    scale_source: 'none',
    mm_per_pt: null,
    engine_version: null,
    page_index: 0,
    revision_id: 'r1',
  },
};

const mount = (patch: Partial<typeof base> = {}) =>
  renderHook((props: typeof base) => useWorkspaceCadStyle(props), {
    initialProps: { ...base, ...patch },
  });

type Hook = ReturnType<typeof mount>;

const start = (hook: Hook) => {
  act(() => hook.result.current.side?.onStartSampling());
};
const click = (hook: Hook, x = 0.2) => {
  act(() => hook.result.current.capture?.onSample({ x, y: 0.3 }));
};
const lastJobId = () => mocks.jobArgs.mock.calls.at(-1)?.[2];

/** Предпросмотр запрошен и задание поставлено. */
const previewed = (hook: Hook) => {
  act(() => hook.result.current.side?.onPreview());
  const options = mocks.createMutate.mock.calls.at(-1)?.[1] as MutateOptions<string>;
  act(() => options.onSuccess?.('job1'));
  mocks.jobData.current = finished;
  hook.rerender({ ...base });
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.jobData.current = undefined;
  mocks.acceptPending.current = false;
});

describe('useWorkspaceCadStyle', () => {
  it('смена листа сбрасывает режим, образцы и предпросмотр', () => {
    const hook = mount();
    start(hook);
    click(hook);
    expect(hook.result.current.side?.samples).toHaveLength(1);
    hook.rerender({ ...base, pageIndex: 1 });
    expect(hook.result.current.side?.sampling).toBe(false);
    expect(hook.result.current.side?.samples).toHaveLength(0);
  });

  it('смена ревизии сбрасывает образцы', () => {
    const hook = mount();
    start(hook);
    click(hook);
    hook.rerender({ ...base, revisionId: 'r2' });
    expect(hook.result.current.side?.samples).toHaveLength(0);
  });

  it('изменение образцов отзывает предпросмотр', () => {
    const hook = mount();
    start(hook);
    click(hook);
    previewed(hook);
    expect(hook.result.current.side?.preview?.result).not.toBeNull();
    click(hook, 0.4);
    expect(hook.result.current.side?.preview).toBeNull();
    expect(lastJobId()).toBeNull();
  });

  it('поздний onSuccess после отзыва не ставит jobId', () => {
    const hook = mount();
    start(hook);
    click(hook);
    act(() => hook.result.current.side?.onPreview());
    const options = mocks.createMutate.mock.calls.at(-1)?.[1] as MutateOptions<string>;
    click(hook, 0.4);
    act(() => options.onSuccess?.('late'));
    expect(lastJobId()).toBeNull();
  });

  it('принятие шлёт base_version предпросмотра, а не версию из кэша профиля', () => {
    const hook = mount();
    start(hook);
    click(hook);
    previewed(hook);
    act(() => hook.result.current.side?.onAccept('Том'));
    expect(mocks.acceptMutate.mock.calls[0]?.[0]).toEqual({
      jobId: 'job1',
      title: 'Том',
      expectedCurrentVersion: 5,
    });
  });

  it('успех принятия: сообщение о версии и выход из режима', () => {
    const hook = mount();
    start(hook);
    click(hook);
    previewed(hook);
    act(() => hook.result.current.side?.onAccept(''));
    const options = mocks.acceptMutate.mock.calls[0]?.[1] as MutateOptions<{ version: number }>;
    act(() => options.onSuccess?.({ version: 7 }));
    expect(hook.result.current.side?.savedVersion).toBe(7);
    expect(hook.result.current.side?.sampling).toBe(false);
    expect(hook.result.current.side?.samples).toHaveLength(0);
  });

  it('Esc (выход из режима) сохраняет образцы, повторный вход возвращает их', () => {
    const hook = mount();
    start(hook);
    click(hook);
    act(() => hook.result.current.capture?.onExit());
    expect(hook.result.current.side?.sampling).toBe(false);
    expect(hook.result.current.capture).toBeNull();
    start(hook);
    expect(hook.result.current.side?.samples).toHaveLength(1);
  });

  it('пока идёт принятие, щелчки и удаление игнорируются', () => {
    const hook = mount();
    start(hook);
    click(hook);
    mocks.acceptPending.current = true;
    hook.rerender({ ...base });
    click(hook, 0.5);
    act(() => hook.result.current.side?.onRemoveSample(0));
    expect(hook.result.current.side?.samples).toHaveLength(1);
  });
});
