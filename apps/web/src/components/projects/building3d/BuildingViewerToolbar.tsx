'use client';

import type { CadBuilding3dGroupRead } from '@quantor/api-client';
import type { FC } from 'react';

import { Button } from '@/components/ui';
import { ALL_GROUPS_KEY } from '@/lib/cad/building-viewer-layout';

interface IBuildingViewerToolbarProps {
  readonly groups: readonly CadBuilding3dGroupRead[];
  /** Выбранная группа или `all` («Весь объект»). */
  readonly groupValue: string;
  readonly onGroupChange: (key: string) => void;
  /** Детальный вид этажа: вместо «Разнести» и «Вписать» - «К зданию». */
  readonly detail: boolean;
  readonly exploded: boolean;
  /** Кнопки холста недоступны: нет этажей с отметкой или холст не запустился. */
  readonly disabled: boolean;
  readonly onToggleExploded: () => void;
  readonly onFit: () => void;
  readonly onBack: () => void;
}

// Высота 32 px от md (как у кнопок), на телефоне - 44 px (min-height из base.css); шрифт поля ≥16 px на телефоне.
const SELECT =
  'h-[44px] w-[200px] min-w-0 flex-none rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text sm:w-[260px] md:h-8 md:text-sm';

/**
 * Верхняя панель просмотрщика: одна строка (на узком экране листается внутри панели, не страницей),
 * корпус, «Разнести этажи», «Вписать» и справа «← К зданию» в детальном виде.
 */
export const BuildingViewerToolbar: FC<IBuildingViewerToolbarProps> = ({
  groups,
  groupValue,
  onGroupChange,
  detail,
  exploded,
  disabled,
  onToggleExploded,
  onFit,
  onBack,
}) => (
  <div className="flex flex-none items-center gap-[var(--s-2)] overflow-x-auto border-b border-border px-[var(--s-4)] py-[var(--s-2)] [overscroll-behavior:contain]">
    {groups.length > 1 && (
      <>
        <label htmlFor="building-group" className="flex-none text-sm text-muted">
          Корпус
        </label>
        <select
          id="building-group"
          value={groupValue}
          onChange={(event) => onGroupChange(event.target.value)}
          className={SELECT}
        >
          <option value={ALL_GROUPS_KEY}>Весь объект</option>
          {groups.map((group) => (
            <option key={group.key} value={group.key}>
              {`${group.label} · ${group.floor_count} эт.`}
            </option>
          ))}
        </select>
      </>
    )}
    {!detail && (
      <>
        <Button
          className="flex-none md:h-8"
          aria-pressed={exploded}
          variant={exploded ? 'primary' : 'default'}
          disabled={disabled}
          onClick={onToggleExploded}
        >
          Разнести этажи
        </Button>
        <Button className="flex-none md:h-8" disabled={disabled} onClick={onFit}>
          Вписать
        </Button>
      </>
    )}
    {detail && (
      <Button className="ml-auto flex-none md:h-8" onClick={onBack}>
        ← К зданию
      </Button>
    )}
  </div>
);
