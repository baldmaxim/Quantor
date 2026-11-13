/** Цвета просмотрщика объекта: только из токенов темы. */

export interface IBuildingViewerColors {
  readonly accent: string;
  readonly muted: string;
  readonly slab: string;
  readonly masonry: string;
  readonly monolith: string;
}

const FALLBACK_COLOR = 'gray';

/** Цвета только из токенов темы: плита, кладка и монолит - как в 3D этажа. */
export const readBuildingViewerColors = (): IBuildingViewerColors => {
  if (typeof document === 'undefined') {
    return {
      accent: FALLBACK_COLOR,
      muted: FALLBACK_COLOR,
      slab: FALLBACK_COLOR,
      masonry: FALLBACK_COLOR,
      monolith: FALLBACK_COLOR,
    };
  }
  const style = getComputedStyle(document.documentElement);
  const token = (name: string): string => style.getPropertyValue(name).trim() || FALLBACK_COLOR;
  return {
    accent: token('--accent'),
    muted: token('--muted'),
    slab: token('--border-strong'),
    masonry: token('--cad-construction-masonry'),
    monolith: token('--cad-construction-monolith'),
  };
};
