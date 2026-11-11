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

/** Левая вкладка: одна и та же в обоих режимах рабочей области. */
export type LeftTab = 'documents' | 'recognition' | 'takeoff';
/** Режим рабочей области: «Листы» или CAD. Меняет правую панель и центр, левая вкладка не трогается. */
export type WorkspaceMode = 'sheets' | 'cad';
export type Tool = 'pointer' | 'pan' | 'scale';

const MIN_LEFT = 200;
const MAX_LEFT = 420;
const MIN_RIGHT = 240;
const MAX_RIGHT = 480;

const clamp = (value: number, min: number, max: number) => Math.min(Math.max(value, min), max);

interface WorkspaceState {
  mode: WorkspaceMode;
  leftTab: LeftTab;
  leftWidth: number | null;
  rightWidth: number | null;
  leftCollapsed: boolean;
  rightCollapsed: boolean;
  tool: Tool;
  overlayVisible: boolean;
  /** Типы областей, скрытые пользователем. Пустое множество — показаны все. */
  hiddenTypes: ReadonlySet<string>;

  setMode: (mode: WorkspaceMode) => void;
  /** `'cad'` - прежний способ открыть режим CAD (`?tab=cad`): включает режим, вкладку не меняет. */
  setLeftTab: (tab: LeftTab | 'cad') => void;
  setLeftWidth: (width: number) => void;
  setRightWidth: (width: number) => void;
  toggleLeft: () => void;
  toggleRight: () => void;
  setTool: (tool: Tool) => void;
  toggleOverlay: () => void;
  toggleType: (type: string) => void;
}

export const useWorkspaceStore = create<WorkspaceState>((set) => ({
  mode: 'sheets',
  leftTab: 'documents',
  // null означает «ширина из токена»: пока пользователь не тянул разделитель,
  // панель должна слушаться дизайн-системы, в том числе на широком мониторе.
  leftWidth: null,
  rightWidth: null,
  leftCollapsed: false,
  rightCollapsed: false,
  tool: 'pointer',
  // Распознанные блоки - второстепенный просмотр: по умолчанию скрыты, включает пользователь.
  overlayVisible: false,
  hiddenTypes: new Set<string>(),

  setMode: (mode) => set({ mode }),
  setLeftTab: (tab) => set(tab === 'cad' ? { mode: 'cad' } : { leftTab: tab }),
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
