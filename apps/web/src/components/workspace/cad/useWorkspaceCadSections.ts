'use client';

import { useMemo, useState } from 'react';

import { cadErrorText } from '@/lib/cad/errors';
import {
  issuesOfPage,
  levelsOfPage,
  sectionsErrorText,
} from '@/lib/cad/sections';
import {
  useCadSections,
  useDecideCadSectionLevels,
  useStartCadSections,
} from '@/lib/cad/sections-queries';
import { readSectionColors, type ISectionPaintData } from '@/lib/cad/sections-painter';
import { useStoredBoolean } from '@/lib/cad/useStoredBoolean';
import { useTheme } from '@/lib/theme';

import type { IWorkspaceCadSections } from './types';

const MARKUP_KEY = 'quantor.cad.sections-markup';

interface IInput {
  projectId: string;
  revisionId: string | null;
  /** Индекс страницы открытого листа. */
  pageIndex: number | null;
  /** Флаг `cad.export` включён и вкладка CAD открывалась хотя бы раз. */
  load: boolean;
  /** Вкладка CAD открыта: разметка рисуется только на ней. */
  active: boolean;
  /** Открыть страницу-разрез в рабочей области. */
  onOpenPage: (pageIndex: number) => void;
}

export interface IWorkspaceCadSectionsState {
  /** Раздел «Разрезы»; `null` - ревизия не открыта. */
  readonly side: IWorkspaceCadSections | null;
  /** Данные слоя разметки; `null` - на листе рисовать нечего или разметка выключена. */
  readonly paintData: ISectionPaintData | null;
  /** Переключатель в «Слоях»; `null` - на листе разрезов нет. */
  readonly layers: { readonly visible: boolean; readonly onVisibleChange: (visible: boolean) => void } | null;
}

/**
 * Разрезы ревизии в рабочей области: чтение результата (с опросом, пока задание идёт), запуск,
 * решения человека по уровням и данные слоя разметки открытого листа. Страницей-разрезом лист
 * считается по ответу сервера (`pages`): паспорт листа для этого не нужен. Разметка кладётся на
 * тот же холст, что DXF и замечания, поэтому видна и на листе, не прошедшем преобразование в CAD.
 */
export const useWorkspaceCadSections = ({
  projectId,
  revisionId,
  pageIndex,
  load,
  active,
  onOpenPage,
}: IInput): IWorkspaceCadSectionsState => {
  const theme = useTheme();
  const colors = useMemo(() => {
    void theme;
    return readSectionColors();
  }, [theme]);

  const query = useCadSections(projectId, revisionId, load);
  const start = useStartCadSections(projectId, revisionId);
  const decide = useDecideCadSectionLevels(projectId, revisionId);
  const [markupVisible, setMarkupVisible] = useStoredBoolean(MARKUP_KEY, true);
  const [selected, setSelected] = useState<string | null>(null);

  const data = query.data ?? null;
  const pageLevels = useMemo(
    () => (data && pageIndex !== null ? levelsOfPage(data.levels, pageIndex) : []),
    [data, pageIndex],
  );
  const pageIssues = useMemo(
    () => (data && pageIndex !== null ? issuesOfPage(data.issues, pageIndex) : []),
    [data, pageIndex],
  );
  // Выбор принадлежит листу: уровень другой страницы не подсвечивается.
  const activeLevelId = pageLevels.some((level) => level.id === selected) ? selected : null;

  const paintData = useMemo<ISectionPaintData | null>(() => {
    if (!active || !markupVisible) return null;
    const issues = pageIssues.filter((issue) => issue.bbox !== null);
    if (pageLevels.length === 0 && issues.length === 0) return null;
    return { levels: pageLevels, issues, colors, activeId: activeLevelId };
  }, [active, markupVisible, pageLevels, pageIssues, colors, activeLevelId]);

  if (revisionId === null) return { side: null, paintData: null, layers: null };

  const actionError = decide.isError
    ? sectionsErrorText(decide.error)
    : start.isError
      ? cadErrorText(start.error)
      : null;

  const side: IWorkspaceCadSections = {
    status: query.isError ? 'error' : data === null ? 'loading' : 'ready',
    data,
    loadError: query.isError ? cadErrorText(query.error) : null,
    onReload: () => void query.refetch(),
    pageIndex,
    isSectionPage:
      data !== null && pageIndex !== null && data.pages.some((item) => item.page_index === pageIndex),
    starting: start.isPending,
    onStart: () => {
      decide.reset();
      start.mutate(null);
    },
    deciding: decide.isPending,
    onDecide: (levelIds, decision) => {
      start.reset();
      decide.mutate({ levelIds, decision });
    },
    actionError,
    activeLevelId,
    onSelectLevel: setSelected,
    markupVisible,
    onMarkupVisibleChange: setMarkupVisible,
    onOpenPage,
  };

  return {
    side,
    paintData,
    layers:
      pageLevels.length > 0 || pageIssues.some((issue) => issue.bbox !== null)
        ? { visible: markupVisible, onVisibleChange: setMarkupVisible }
        : null,
  };
};
