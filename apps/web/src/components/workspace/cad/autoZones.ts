import type { IWorkspaceCadPipeline } from './useWorkspaceCadPipeline';
import type { IWorkspaceCadAutoZones } from './types';

/**
 * Автоматическая разметка зон для раздела «Зоны» из конвейера открытого листа.
 * `null` - запускать нечего: нет задания преобразования или вида с DXF (как у `startAutoZones`).
 */
export const autoZonesOf = ({
  sheet,
  startAutoZones,
  startingZones,
  zonesError,
}: Pick<
  IWorkspaceCadPipeline,
  'sheet' | 'startAutoZones' | 'startingZones' | 'zonesError'
>): IWorkspaceCadAutoZones | null => {
  const view = sheet?.views.find((row) => row.has_dxf);
  if (!sheet || !view || !sheet.convert?.job_id) return null;
  const status = view.zones?.status;
  return {
    onStart: () => void startAutoZones(),
    starting: startingZones || status === 'queued' || status === 'running',
    error: zonesError,
  };
};
