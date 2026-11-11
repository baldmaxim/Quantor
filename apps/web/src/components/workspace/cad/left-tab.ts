import type { LeftTab, WorkspaceMode } from '@/store/workspace';

/**
 * Какая левая вкладка действительно открыта. Выключенный пилот или показ распознанных блоков
 * закрывают свою вкладку: запомненный выбор не открывает возможность, а уступает место листам,
 * при этом хранилище не переписывается - включение флага вернёт человека туда, где он был.
 */
export const resolveLeftTab = (
  tab: LeftTab,
  access: { readonly takeoff: boolean; readonly recognition: boolean },
): LeftTab => {
  if (tab === 'takeoff' && !access.takeoff) return 'documents';
  if (tab === 'recognition' && !access.recognition) return 'documents';
  return tab;
};

/** Режим CAD закрыт флагом `cad.export`: запомненный выбор уступает место режиму «Листы». */
export const resolveMode = (mode: WorkspaceMode, cadEnabled: boolean): WorkspaceMode =>
  mode === 'cad' && !cadEnabled ? 'sheets' : mode;

/** Режим из адреса (`?tab=cad`); незнакомое значение - `null`, ничего не угадываем. */
export const tabFromQuery = (value: string | null): 'cad' | null =>
  value === 'cad' ? 'cad' : null;
