import { render } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

import type { IModelPartInput } from '@/lib/model/model-scene';
import { createSpeckleModelViewer, type ISpeckleModelViewer } from '@/lib/model/model-speckle';

import { ModelSpeckleCanvas } from './ModelSpeckleCanvas';

vi.mock('@/lib/model/model-speckle', () => ({ createSpeckleModelViewer: vi.fn() }));

const fakeViewer = (): ISpeckleModelViewer => ({
  setContent: vi.fn(() => Promise.resolve(true)),
  setDisciplineVisible: vi.fn(),
  select: vi.fn(),
  setColorByCategory: vi.fn(),
  fit: vi.fn(),
  dispose: vi.fn(),
});

const part = (key: string, discipline = 'ARCH'): IModelPartInput => ({
  key,
  discipline,
  buffer: new ArrayBuffer(8),
});

const props = (parts: readonly IModelPartInput[]) => ({
  parts,
  elements: null,
  hiddenDisciplines: new Set<string>(),
  selectedId: null,
  colorByCategory: false,
  fitSeq: 0,
  onPick: vi.fn(),
  onError: vi.fn(),
});

describe('холст Speckle: перезагрузка содержимого', () => {
  let viewer: ISpeckleModelViewer;
  beforeEach(() => {
    viewer = fakeViewer();
    vi.mocked(createSpeckleModelViewer).mockResolvedValue(viewer);
  });

  const mounted = async (parts: readonly IModelPartInput[]) => {
    const view = render(<ModelSpeckleCanvas {...props(parts)} />);
    await vi.waitFor(() => expect(viewer.setContent).toHaveBeenCalledTimes(1));
    return view;
  };

  it('тот же состав частей в новом массиве модель не перезагружает', async () => {
    const view = await mounted([part('a'), part('b', 'PL')]);
    view.rerender(<ModelSpeckleCanvas {...props([part('a'), part('b', 'PL')])} selectedId="gid" />);
    view.rerender(<ModelSpeckleCanvas {...props([part('a'), part('b', 'PL')])} colorByCategory />);
    await Promise.resolve();
    expect(viewer.setContent).toHaveBeenCalledTimes(1);
    expect(viewer.select).toHaveBeenLastCalledWith(null);
  });

  it('щелчок и раскраска меняют выбор и цвет, не содержимое', async () => {
    const view = await mounted([part('a')]);
    view.rerender(<ModelSpeckleCanvas {...props([part('a')])} selectedId="gid-1" />);
    expect(viewer.select).toHaveBeenLastCalledWith('gid-1');
    view.rerender(<ModelSpeckleCanvas {...props([part('a')])} colorByCategory />);
    expect(viewer.setColorByCategory).toHaveBeenLastCalledWith(true);
    expect(viewer.setContent).toHaveBeenCalledTimes(1);
  });

  it('другой состав частей (другой этаж) загружается заново', async () => {
    const view = await mounted([part('a')]);
    view.rerender(<ModelSpeckleCanvas {...props([part('c')])} />);
    await vi.waitFor(() => expect(viewer.setContent).toHaveBeenCalledTimes(2));
  });

  it('просмотрщик освобождается при размонтировании', async () => {
    const view = await mounted([part('a')]);
    view.unmount();
    expect(viewer.dispose).toHaveBeenCalled();
  });
});
