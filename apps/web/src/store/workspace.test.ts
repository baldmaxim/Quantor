import { beforeEach, describe, expect, it } from 'vitest';

import { useWorkspaceStore } from './workspace';

beforeEach(() => useWorkspaceStore.setState({ mode: 'sheets', leftTab: 'documents' }));

describe('хранилище рабочей области: режим и левая вкладка', () => {
  it('режим CAD не меняет левую вкладку, и наоборот', () => {
    const store = useWorkspaceStore.getState();
    store.setMode('cad');
    expect(useWorkspaceStore.getState()).toMatchObject({ mode: 'cad', leftTab: 'documents' });

    store.setLeftTab('takeoff');
    expect(useWorkspaceStore.getState()).toMatchObject({ mode: 'cad', leftTab: 'takeoff' });

    store.setMode('sheets');
    expect(useWorkspaceStore.getState()).toMatchObject({ mode: 'sheets', leftTab: 'takeoff' });
  });

  it('setLeftTab("cad") (адрес ?tab=cad) включает режим, вкладку не трогает', () => {
    useWorkspaceStore.getState().setLeftTab('recognition');
    useWorkspaceStore.getState().setLeftTab('cad');
    expect(useWorkspaceStore.getState()).toMatchObject({ mode: 'cad', leftTab: 'recognition' });
  });
});
