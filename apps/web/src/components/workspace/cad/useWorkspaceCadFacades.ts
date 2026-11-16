'use client';

import { useMemo, useState } from 'react';

import { cadErrorText } from '@/lib/cad/errors';
import type { IFacadePaintData } from '@/lib/cad/facades-painter';
import {
  useCadFacades,
  useDecideCadFacadeViews,
  useStartCadFacades,
} from '@/lib/cad/facades-queries';
import { readSectionColors } from '@/lib/cad/sections-painter';
import { useTheme } from '@/lib/theme';

import type { IWorkspaceCadFacades } from './types';

interface IInput {
  projectId: string;
  revisionId: string | null;
  /** Индекс страницы открытого листа. */
  pageIndex: number | null;
  /** Флаг `cad.export` включён и вкладка CAD открывалась хотя бы раз. */
  load: boolean;
  /** Вкладка CAD открыта: разметка рисуется только на ней. */
  active: boolean;
  /** Открыть страницу вида в рабочей области. */
  onOpenPage: (pageIndex: number) => void;
}

export interface IWorkspaceCadFacadesState {
  /** Раздел «Фасады»; `null` - ревизия не открыта. */
  readonly side: IWorkspaceCadFacades | null;
  /** Данные слоя разметки; `null` - вкладка «Фасады» закрыта или на листе видов нет. */
  readonly paintData: IFacadePaintData | null;
}

/**
 * Фасады ревизии в рабочей области: чтение результата (с опросом, пока задание идёт), запуск,
 * решения человека по видам и данные слоя разметки открытого листа. Разметка видна только при
 * открытой вкладке «Фасады» (панель сообщает об этом через `onPanelShown`).
 */
export const useWorkspaceCadFacades = ({
  projectId,
  revisionId,
  pageIndex,
  load,
  active,
  onOpenPage,
}: IInput): IWorkspaceCadFacadesState => {
  const theme = useTheme();
  const colors = useMemo(() => {
    void theme;
    return readSectionColors();
  }, [theme]);

  const query = useCadFacades(projectId, revisionId, load);
  const start = useStartCadFacades(projectId, revisionId);
  const decide = useDecideCadFacadeViews(projectId, revisionId);
  const [selected, setSelected] = useState<string | null>(null);
  const [shown, setShown] = useState(false);

  const data = query.data ?? null;
  const pageViews = useMemo(
    () =>
      data && pageIndex !== null ? data.views.filter((view) => view.page_index === pageIndex) : [],
    [data, pageIndex],
  );
  // Выбор принадлежит листу: вид другой страницы не подсвечивается.
  const activeViewId = pageViews.some((view) => view.id === selected) ? selected : null;

  const paintData = useMemo<IFacadePaintData | null>(() => {
    if (!active || !shown || pageViews.length === 0) return null;
    return { views: pageViews, colors, activeId: activeViewId };
  }, [active, shown, pageViews, colors, activeViewId]);

  if (revisionId === null) return { side: null, paintData: null };

  const actionError = decide.isError
    ? cadErrorText(decide.error)
    : start.isError
      ? cadErrorText(start.error)
      : null;

  const side: IWorkspaceCadFacades = {
    status: query.isError ? 'error' : data === null ? 'loading' : 'ready',
    data,
    loadError: query.isError ? cadErrorText(query.error) : null,
    onReload: () => void query.refetch(),
    pageIndex,
    starting: start.isPending,
    onStart: () => {
      decide.reset();
      start.mutate();
    },
    deciding: decide.isPending,
    onDecide: (viewIds, decision) => {
      start.reset();
      decide.mutate({ viewIds, decision });
    },
    actionError,
    activeViewId,
    onSelectView: setSelected,
    onPanelShown: setShown,
    onOpenPage,
  };
  return { side, paintData };
};
