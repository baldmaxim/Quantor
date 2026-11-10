import { act, render, screen } from '@testing-library/react';
import { Suspense } from 'react';
import { beforeEach, describe, expect, it, vi } from 'vitest';

const REVISION = '11111111-1111-4111-8111-111111111111';
const JOB = '22222222-2222-4222-8222-222222222222';

const mocks = vi.hoisted(() => ({
  replace: vi.fn(),
  query: '',
  metaLoaded: true,
  features: { 'cad.export': true } as Record<string, boolean>,
  sheets: { isPending: false, data: undefined as unknown },
  sheetsArg: vi.fn(),
}));

vi.mock('next/navigation', () => ({
  useRouter: () => ({ replace: mocks.replace }),
  useSearchParams: () => new URLSearchParams(mocks.query),
}));
vi.mock('@/lib/queries', () => ({
  useMeta: () => ({ isSuccess: mocks.metaLoaded }),
  useFeatures: () => mocks.features,
  useSheets: (revisionId: string | null) => {
    mocks.sheetsArg(revisionId);
    return mocks.sheets;
  },
}));

import CadPage from './page';

const mount = async () => {
  await act(async () => {
    render(
      <Suspense fallback={<p>ждём</p>}>
        <CadPage params={Promise.resolve({ projectId: 'p1' })} />
      </Suspense>,
    );
  });
};

beforeEach(() => {
  vi.clearAllMocks();
  mocks.query = '';
  mocks.metaLoaded = true;
  mocks.features = { 'cad.export': true };
  mocks.sheets = { isPending: false, data: undefined };
});

describe('страница CAD: перевод в рабочую область', () => {
  it('без ревизии - вкладка CAD рабочей области', async () => {
    await mount();
    expect(mocks.replace).toHaveBeenCalledWith('/projects/p1/workspace?tab=cad', {
      scroll: false,
    });
  });

  it('задание, лист и вид: индекс страницы становится позицией листа', async () => {
    mocks.query = `revision=${REVISION}&job=${JOB}&page=4&view=2`;
    mocks.sheets = {
      isPending: false,
      data: { items: [{ page_index: 0 }, { page_index: 4 }] },
    };
    await mount();
    expect(mocks.sheetsArg).toHaveBeenCalledWith(REVISION);
    expect(mocks.replace).toHaveBeenCalledTimes(1);
    expect(mocks.replace).toHaveBeenCalledWith(
      `/projects/p1/workspace?revision=${REVISION}&page=2&tab=cad&job=${JOB}&view=2`,
      { scroll: false },
    );
  });

  it('листы ещё грузятся - перевода нет', async () => {
    mocks.query = `revision=${REVISION}&job=${JOB}&page=4&view=2`;
    mocks.sheets = { isPending: true, data: undefined };
    await mount();
    expect(mocks.replace).not.toHaveBeenCalled();
  });

  it('листов нет (отказ) - позиция по индексу, перевод не зависает', async () => {
    mocks.query = `revision=${REVISION}&job=${JOB}&page=4`;
    await mount();
    expect(mocks.replace).toHaveBeenCalledWith(
      `/projects/p1/workspace?revision=${REVISION}&page=5&tab=cad&job=${JOB}`,
      { scroll: false },
    );
  });

  it('только ревизия: листы не запрашиваются', async () => {
    mocks.query = `revision=${REVISION}`;
    await mount();
    expect(mocks.sheetsArg).toHaveBeenCalledWith(null);
    expect(mocks.replace).toHaveBeenCalledWith(
      `/projects/p1/workspace?revision=${REVISION}&tab=cad`,
      { scroll: false },
    );
  });

  it('флаг cad.export выключен: страницы нет, перевода нет', async () => {
    mocks.features = {};
    await mount();
    expect(screen.getByText('Страница не найдена')).toBeInTheDocument();
    expect(mocks.replace).not.toHaveBeenCalled();
  });

  it('мета не пришла - ждём, перевода нет', async () => {
    mocks.metaLoaded = false;
    await mount();
    expect(mocks.replace).not.toHaveBeenCalled();
  });
});
