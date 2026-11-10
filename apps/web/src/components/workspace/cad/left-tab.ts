import type { LeftTab } from '@/store/workspace';

/**
 * Какая левая вкладка действительно открыта. Выключенный пилот или флаг `cad.export` закрывают
 * свою вкладку: запомненный выбор не открывает возможность, а уступает место листам, при этом
 * хранилище не переписывается - включение флага вернёт человека туда, где он был.
 */
export const resolveLeftTab = (
  tab: LeftTab,
  access: { readonly takeoff: boolean; readonly cad: boolean },
): LeftTab => {
  if (tab === 'takeoff' && !access.takeoff) return 'documents';
  if (tab === 'cad' && !access.cad) return 'documents';
  return tab;
};

/** Вкладка из адреса (`?tab=cad`); незнакомое значение - `null`, ничего не угадываем. */
export const tabFromQuery = (value: string | null): LeftTab | null =>
  value === 'cad' ? 'cad' : null;
