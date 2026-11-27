import { act, renderHook } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { ICadRemarks } from '@/components/cad/viewer/useCadRemarks';
import type { IRemark, IRemarkBinding } from '@/lib/cad/remarks';
import { resetStoredNumbers } from '@/lib/cad/useStoredNumber';
import { WORKSPACE_DRAFT_ID } from '@/lib/cad/workspace-cad';
import { Camera } from '@/lib/viewer/camera';

import { useWorkspaceCadRemarks } from './useWorkspaceCadRemarks';

const mockUseCadRemarks = vi.fn<() => ICadRemarks>();

vi.mock('@/components/cad/viewer/useCadRemarks', () => ({
  useCadRemarks: () => mockUseCadRemarks(),
}));

const BINDING: IRemarkBinding = {
  projectId: 'p1',
  revisionId: 'r1',
  jobId: 'j1',
  attempt: 1,
  pageIndex: 0,
  legacyPdfPage: 1,
  view: 1,
  dxfSha256: 'sha256',
};

const PAGE_SIZE = { width: 1000, height: 500 };

const REMARKS: readonly IRemark[] = [
  {
    id: 'rem-1',
    type: 'missing_wall',
    comment: 'Нет стены',
    reviewer: 'Иван',
    status: 'open',
    bbox_pt: [100, 50, 200, 150],
    created_at: '2026-01-01T00:00:00Z',
    updated_at: '2026-01-01T00:00:00Z',
  },
  {
    id: 'rem-2',
    type: 'false_wall',
    comment: 'Лишняя стена',
    reviewer: 'Иван',
    status: 'resolved',
    bbox_pt: [300, 100, 400, 200],
    created_at: '2026-01-01T00:01:00Z',
    updated_at: '2026-01-01T00:01:00Z',
  },
];

const makeStore = (remarks: readonly IRemark[]): ICadRemarks => ({
  remarks,
  loading: false,
  loadError: null,
  reload: vi.fn(),
  reviewer: 'Иван',
  setReviewer: vi.fn(),
  saving: false,
  error: null,
  add: vi.fn(async () => null),
  update: vi.fn(),
  remove: vi.fn(),
  importFile: vi.fn(async () => ({ imported: 0, updated: 0 })),
});

describe('useWorkspaceCadRemarks', () => {
  beforeEach(() => {
    window.localStorage.clear();
    resetStoredNumbers();
    mockUseCadRemarks.mockReturnValue(makeStore(REMARKS));
  });

  const mountHook = (active = true) =>
    renderHook(() =>
      useWorkspaceCadRemarks({
        binding: BINDING,
        pageSize: PAGE_SIZE,
        camera: new Camera(),
        viewportSize: () => ({ width: 800, height: 600 }),
        active,
      }),
    );

  it('по умолчанию показывает рамки всех замечаний и отдаёт layers.visible === true', () => {
    const { result } = mountHook();

    expect(result.current.marks).toHaveLength(2);
    expect(result.current.marks.map((m) => [m.id, m.number])).toEqual([
      ['rem-1', 1],
      ['rem-2', 2],
    ]);
    expect(result.current.layers?.visible).toBe(true);
    expect(result.current.remarks?.marksVisible).toBe(true);
  });

  it('при скрытии рамок marks пуст, layers.visible === false и выбор сохраняется в localStorage', () => {
    const { result } = mountHook();

    act(() => {
      result.current.remarks?.onMarksVisibleChange?.(false);
    });

    expect(result.current.marks).toEqual([]);
    expect(result.current.layers?.visible).toBe(false);
    expect(result.current.remarks?.marksVisible).toBe(false);
    expect(window.localStorage.getItem('quantor.cad.remarks-visible')).toBe('0');
  });

  it('при скрытых рамках черновик после onDrawn виден с номером remarks.length + 1', () => {
    const { result } = mountHook();

    act(() => {
      result.current.layers?.onVisibleChange(false);
    });
    expect(result.current.marks).toEqual([]);

    act(() => {
      result.current.onDrawn([500, 100, 600, 200]);
    });

    expect(result.current.marks).toHaveLength(1);
    expect(result.current.marks[0]?.id).toBe(WORKSPACE_DRAFT_ID);
    expect(result.current.marks[0]?.number).toBe(REMARKS.length + 1);
  });

  it('без замечаний на виде layers === null', () => {
    mockUseCadRemarks.mockReturnValue(makeStore([]));
    const { result } = mountHook();

    expect(result.current.layers).toBeNull();
    expect(result.current.marks).toEqual([]);
  });
});
