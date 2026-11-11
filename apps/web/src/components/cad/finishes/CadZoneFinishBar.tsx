'use client';

import { useState, type FC } from 'react';

import type { CadFinishTemplateRead, CadZoneRead } from '@quantor/api-client';

import { Button } from '@/components/ui';
import { ROOM_TYPE_LABELS, type RoomType } from '@/lib/cad/room-types';

export interface IFinishAssignOutcome {
  readonly assigned: number;
  readonly skipped: number;
}

interface ICadZoneFinishBarProps {
  /** Зоны-помещения листа: только их можно выбирать (у двери и машино-места отделки нет). */
  zones: readonly CadZoneRead[];
  checked: ReadonlySet<string>;
  onCheckedChange: (ids: ReadonlySet<string>) => void;
  templates: readonly CadFinishTemplateRead[];
  assigning: boolean;
  error: string | null;
  /** Назначить шаблон выбранным зонам; `null` снимает явное назначение. `null` в ответе - отказ. */
  onAssign: (
    zoneIds: readonly string[],
    templateId: string | null,
  ) => Promise<IFinishAssignOutcome | null>;
}

const FIELD =
  'h-[var(--h-ctl)] max-md:h-[44px] w-full min-w-0 rounded-[var(--radius-sm)] border border-border-control bg-surface px-[var(--s-4)] text-base text-text md:text-sm';

const CLEAR_EXPLICIT = '__clear__';

/**
 * Панель массового выбора зон над списком: «выбрать все», «выбрать по типу», «Назначить шаблон…».
 * Выбор живёт в списке зон; здесь - действия над ним.
 */
export const CadZoneFinishBar: FC<ICadZoneFinishBarProps> = ({
  zones,
  checked,
  onCheckedChange,
  templates,
  assigning,
  error,
  onAssign,
}) => {
  const [picking, setPicking] = useState(false);
  const [templateId, setTemplateId] = useState('');
  const [message, setMessage] = useState<string | null>(null);

  const typeCounts = new Map<RoomType, number>();
  for (const zone of zones) {
    if (zone.room_type !== null) {
      typeCounts.set(zone.room_type, (typeCounts.get(zone.room_type) ?? 0) + 1);
    }
  }
  const selectedIds = zones.filter((zone) => checked.has(zone.id)).map((zone) => zone.id);

  const submit = async () => {
    if (templateId === '' || selectedIds.length === 0) return;
    const outcome = await onAssign(selectedIds, templateId === CLEAR_EXPLICIT ? null : templateId);
    if (outcome === null) return;
    setMessage(
      outcome.skipped > 0
        ? `Назначено зонам: ${outcome.assigned}, пропущено: ${outcome.skipped}.`
        : `Назначено зонам: ${outcome.assigned}.`,
    );
    setPicking(false);
    setTemplateId('');
    onCheckedChange(new Set());
  };

  return (
    <div
      className="flex min-w-0 flex-col gap-[var(--s-3)] rounded-[var(--radius-sm)] border border-border p-[var(--s-3)]"
      data-testid="cad-zone-finish-bar"
    >
      <div className="flex flex-wrap items-center gap-[var(--s-2)]">
        <Button
          compact
          variant="ghost"
          className="max-md:h-[44px]"
          onClick={() => {
            setMessage(null);
            onCheckedChange(new Set(zones.map((zone) => zone.id)));
          }}
        >
          Выбрать все на листе
        </Button>
        <Button
          compact
          variant="ghost"
          disabled={checked.size === 0}
          className="max-md:h-[44px]"
          onClick={() => onCheckedChange(new Set())}
        >
          Снять выбор
        </Button>
      </div>

      {typeCounts.size > 0 && (
        <select
          aria-label="Выбрать зоны по типу помещения"
          value=""
          className={FIELD}
          onChange={(event) => {
            const type = [...typeCounts.keys()].find((code) => code === event.target.value);
            if (type === undefined) return;
            setMessage(null);
            onCheckedChange(
              new Set(zones.filter((zone) => zone.room_type === type).map((zone) => zone.id)),
            );
          }}
        >
          <option value="" disabled>
            Выбрать по типу…
          </option>
          {[...typeCounts].map(([type, count]) => (
            <option key={type} value={type}>
              {ROOM_TYPE_LABELS[type]} ({count})
            </option>
          ))}
        </select>
      )}

      <p className="text-xs text-muted" role="status">
        Выбрано зон: {selectedIds.length}
      </p>

      {picking ? (
        <div className="flex min-w-0 flex-col gap-[var(--s-2)]">
          <select
            aria-label="Шаблон отделки для назначения"
            value={templateId}
            className={FIELD}
            onChange={(event) => setTemplateId(event.target.value)}
          >
            <option value="" disabled>
              Выберите шаблон…
            </option>
            {templates.map((template) => (
              <option key={template.id} value={template.id}>
                {template.name}
              </option>
            ))}
            <option value={CLEAR_EXPLICIT}>Снять явное назначение (шаблон по типу)</option>
          </select>
          <div className="flex flex-wrap gap-[var(--s-2)]">
            <Button
              compact
              variant="primary"
              disabled={assigning || templateId === '' || selectedIds.length === 0}
              className="max-md:h-[44px]"
              onClick={() => void submit()}
            >
              Назначить
            </Button>
            <Button compact className="max-md:h-[44px]" onClick={() => setPicking(false)}>
              Отмена
            </Button>
          </div>
        </div>
      ) : (
        <Button
          compact
          disabled={selectedIds.length === 0 || assigning}
          className="self-start max-md:h-[44px]"
          onClick={() => {
            setMessage(null);
            setPicking(true);
          }}
        >
          Назначить шаблон…
        </Button>
      )}
      {picking && templates.length === 0 && (
        <p className="text-xs text-muted">Шаблонов пока нет: создайте их в разделе «Отделка».</p>
      )}

      {message !== null && (
        <p role="status" className="text-xs">
          {message}
        </p>
      )}
      {error !== null && (
        <p role="alert" className="text-xs text-danger">
          {error}
        </p>
      )}
    </div>
  );
};
