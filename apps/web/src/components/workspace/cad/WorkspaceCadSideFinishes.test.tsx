import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';

const panel = vi.hoisted(() => vi.fn());

vi.mock('@/components/cad/finishes/CadFinishPanel', () => ({
  CadFinishPanel: (props: {
    load: boolean;
    pageIndex: number | null;
    onOpenTab?: (id: 'zones' | 'constructions') => void;
  }) => {
    panel(props);
    return (
      <button type="button" onClick={() => props.onOpenTab?.('zones')}>
        панель отделки
      </button>
    );
  },
}));
vi.mock('@/components/cad/viewer/CadZonesPanel', () => ({
  CadZonesPanel: () => <p>панель зон</p>,
}));
// Сверка зон читает сервер: в тесте раздела «Отделка» она не нужна.
vi.mock('@/components/cad/viewer/CadZonesQuality', () => ({ CadZonesQuality: () => null }));
vi.mock('@/components/cad/CadJobDetail', () => ({ CadJobDetail: () => <p>ход задания</p> }));
vi.mock('@/components/cad/CadResult', () => ({ CadResult: () => <p>результат</p> }));
vi.mock('@/components/cad/viewer/CadFilesSection', () => ({ CadFilesSection: () => <p>файлы</p> }));

import type { IWorkspaceCadSideProps, IWorkspaceCadZones } from './types';
import { WorkspaceCadSide } from './WorkspaceCadSide';

const ZONES = { activeId: 'z1', onActivate: vi.fn() } as unknown as IWorkspaceCadZones;
const FINISHES = { projectId: 'p1', revisionId: 'r1', pageIndex: 3, load: true };

const mount = (patch: Partial<IWorkspaceCadSideProps> = {}) =>
  render(
    <WorkspaceCadSide
      state="none"
      sheetLabel="1"
      loadError={null}
      onRetry={vi.fn()}
      job={null}
      convert={null}
      viewLoading={false}
      viewError={null}
      view={null}
      zones={ZONES}
      finishes={FINISHES}
      {...patch}
    />,
  );

describe('раздел «Отделка» правой панели CAD', () => {
  it('лист без задания: «Отделка» после «Зон», открыт последний «Лист»', () => {
    mount();
    expect(screen.getAllByRole('tab').map((tab) => tab.textContent)).toEqual([
      'Зоны',
      'Отделка',
      'Лист',
    ]);
    expect(screen.getByRole('tab', { name: 'Лист' })).toHaveAttribute('aria-selected', 'true');
    // Открыт «Лист»: ведомость отделки не читается.
    expect(panel.mock.calls.at(-1)?.[0]).toMatchObject({ load: false });
  });

  it('переход из «Отделки» открывает «Зоны»', () => {
    mount();
    fireEvent.click(screen.getByRole('tab', { name: 'Отделка' }));
    fireEvent.click(screen.getByText('панель отделки'));
    expect(screen.getByRole('tab', { name: 'Зоны' })).toHaveAttribute('aria-selected', 'true');
    expect(panel.mock.calls.at(-1)?.[0]).toMatchObject({ load: false });
  });

  it('ведомость не читается, пока раздел закрыт; открытие включает чтение листа', () => {
    mount();
    expect(panel.mock.calls.at(-1)?.[0]).toMatchObject({ load: false, pageIndex: 3 });
    fireEvent.click(screen.getByRole('tab', { name: 'Отделка' }));
    expect(panel.mock.calls.at(-1)?.[0]).toMatchObject({ load: true, pageIndex: 3 });
    expect(screen.getByText('панель отделки')).toBeVisible();
  });

  it('без зон или без finishes раздела нет', () => {
    mount({ finishes: null });
    expect(screen.queryByRole('tab', { name: 'Отделка' })).toBeNull();
  });
});
