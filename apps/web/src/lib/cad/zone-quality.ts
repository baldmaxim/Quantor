import type { CadZoneRead } from '@quantor/api-client';

import type { BadgeTone } from '@/components/ui';

/** Итог сверки зоны с экспликацией листа: подписи, тон и выборка зон вне допуска (без UI-логики). */

export type ZoneQualityStatus = CadZoneRead['quality_status'];

export const ZONE_QUALITY_LABELS: Readonly<Record<ZoneQualityStatus, string>> = {
  ok: 'в допуске',
  review: 'на проверку',
  failed: 'отклонена',
};

export const zoneQualityTone = (status: ZoneQualityStatus): BadgeTone => {
  if (status === 'failed') return 'danger';
  return status === 'review' ? 'warning' : 'success';
};

/** Зоны вне допуска: сначала отклонённые (не участвуют в расчётах), затем «на проверку». */
export const zonesOutOfTolerance = (zones: readonly CadZoneRead[]): CadZoneRead[] =>
  zones
    .filter((zone) => zone.quality_status !== 'ok')
    .sort((a, b) => Number(b.quality_status === 'failed') - Number(a.quality_status === 'failed'));
