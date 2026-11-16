'use client';

import { useMemo, type FC } from 'react';

import { CadLayerGroup } from '@/components/cad/viewer/CadLayerGroup';

/** Строка расчёта в группе «Расчёты» панели «Слои». */
export interface ICadTenderLayerItem {
  readonly calcId: string;
  /** Название строки: «Отопление · №3 v3». */
  readonly title: string;
  /** Значение цвета образца (`var(--tender-sys-…)`). */
  readonly color: string;
  readonly visible: boolean;
  /** База объекта перестроена после выпуска: на плане координаты могут быть смещены. */
  readonly baseStale: boolean;
}

export interface ICadTenderLayers {
  readonly items: readonly ICadTenderLayerItem[];
  /** Показать или скрыть расчёты по идентификаторам; хранится в общем хранилище видимости слоёв CAD. */
  readonly onSetVisible: (calcIds: readonly string[], visible: boolean) => void;
}

/**
 * Группа «Расчёты» панели «Слои» (ADR-0051): строка на действующую версию расчёта, флажок видимости
 * и значок «база устарела». Видимость общая у плана и 3D этажа.
 */
export const CadTenderLayers: FC<ICadTenderLayers> = ({ items, onSetVisible }) => {
  const group = useMemo(
    () => ({ key: 'tender', label: 'Расчёты', indices: items.map((_, index) => index) }),
    [items],
  );
  const titles = useMemo(() => items.map((item) => item.title), [items]);
  const visible = useMemo(
    () => new Set(items.flatMap((item, index) => (item.visible ? [index] : []))),
    [items],
  );
  const idsOf = (indices: readonly number[]): string[] =>
    indices.flatMap((index) => (items[index] ? [items[index].calcId] : []));

  return (
    <fieldset className="min-w-0 border-0 p-0" data-testid="tender-layers">
      <legend className="sr-only">Расчёты систем из TENDER</legend>
      <CadLayerGroup
        group={group}
        layers={titles}
        visibleLayers={visible}
        onToggleLayer={(index) => onSetVisible(idsOf([index]), !visible.has(index))}
        onSetLayersHidden={(indices, hidden) => onSetVisible(idsOf(indices), !hidden)}
        swatchColor={(index) => items[index]?.color ?? 'var(--muted)'}
        noteOf={(index) => (items[index]?.baseStale ? 'база устарела' : null)}
      />
    </fieldset>
  );
};
