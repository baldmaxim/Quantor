'use client';

import { create } from 'zustand';

/**
 * Эфемерное состояние рабочей области.
 *
 * Здесь только то, что не является ни серверными данными, ни адресом страницы:
 * ширина и свёрнутость панелей, активная вкладка, видимость типов областей.
 *
 * Камера и высокочастотные преобразования сюда не попадают намеренно — они живут
 * в собственном контроллере, потому что обновляются десятки раз в секунду (ADR-0004).
 * Что видит пользователь — лист, документ, выбранная область — живёт в URL, чтобы
 * ссылка на конкретный лист работала.
 */

export type LeftTab = 'documents' | 'recognition' | 'takeoff';
export type Tool = 'pointer' | 'pan' | 'scale';

const MIN_LEFT = 200;
const MAX_LEFT = 420;
const MIN_RIGHT = 240;
const MAX_RIGHT = 480;

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

interface WorkspaceState {
  leftTab: LeftTab;
  leftWidth: number | null;
  rightWidth: number | null;
  leftCollapsed: boolean;
  rightCollapsed: boolean;
  tool: Tool;
  overlayVisible: boolean;
  /** Типы областей, скрытые пользователем. Пустое множество — показаны все. */
  hiddenTypes: ReadonlySet<string>;

  setLeftTab: (tab: LeftTab) => void;
  setLeftWidth: (width: number) => void;
  setRightWidth: (width: number) => void;
  toggleLeft: () => void;
  toggleRight: () => void;
  setTool: (tool: Tool) => void;
  toggleOverlay: () => void;
  toggleType: (type: string) => void;
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  leftTab: 'documents',
  // null означает «ширина из токена»: пока пользователь не тянул разделитель,
  // панель должна слушаться дизайн-системы, в том числе на широком мониторе.
  leftWidth: null,
  rightWidth: null,
  leftCollapsed: false,
  rightCollapsed: false,
  tool: 'pointer',
  overlayVisible: true,
  hiddenTypes: new Set<string>(),

  setLeftTab: (leftTab) => set({ leftTab }),
  setLeftWidth: (width) => set({ leftWidth: clamp(width, MIN_LEFT, MAX_LEFT) }),
  setRightWidth: (width) => set({ rightWidth: clamp(width, MIN_RIGHT, MAX_RIGHT) }),
  toggleLeft: () => set((state) => ({ leftCollapsed: !state.leftCollapsed })),
  toggleRight: () => set((state) => ({ rightCollapsed: !state.rightCollapsed })),
  setTool: (tool) => set({ tool }),
  toggleOverlay: () => set((state) => ({ overlayVisible: !state.overlayVisible })),
  toggleType: (type) =>
    set((state) => {
      const next = new Set(state.hiddenTypes);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      return { hiddenTypes: next };
    }),
}));

export const PANE_LIMITS = { MIN_LEFT, MAX_LEFT, MIN_RIGHT, MAX_RIGHT } as const;
