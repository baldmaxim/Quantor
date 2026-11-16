'use client';

import type { CadBuilding3dGroupRead } from '@quantor/api-client';
import { useState, type FC } from 'react';

import { Button, Dialog, DialogActions } from '@/components/ui';
import { cadErrorText } from '@/lib/cad/errors';
import { useRevokeSitePin } from '@/lib/cad/site-pin-queries';

interface IBuildingGroupPlacementProps {
  readonly projectId: string;
  readonly group: CadBuilding3dGroupRead;
  /** Есть право записи в CAD и включён `cad.export`: без него кнопок нет. */
  readonly canEdit: boolean;
  readonly onPin: (group: CadBuilding3dGroupRead) => void;
}

/** Подпись способа посадки у ручной привязки. */
export const MANUAL_PLACEMENT_LABEL = 'Привязан вручную';

/**
 * Состояние посадки здания в списке: не поставлен - причина и «Привязать вручную»; привязан вручную -
 * подпись, сообщение сервера (с невязкой) и «Снять привязку» с подтверждением. Остальные способы
 * посадки ничего не показывают.
 */
export const BuildingGroupPlacement: FC<IBuildingGroupPlacementProps> = ({ projectId, group, canEdit, onPin }) => {
  const [confirming, setConfirming] = useState(false);
  const revoke = useRevokeSitePin(projectId);
  const message = group.placement_message ? `: ${group.placement_message}` : '';

  if (group.placement === 'none') {
    return (
      <div className="flex flex-col items-start gap-[var(--s-2)] px-[var(--s-4)] pb-[var(--s-2)]">
        <p className="text-xs text-warning [overflow-wrap:anywhere]">Не поставлен на объект{message}</p>
        {canEdit && (
          <Button className="min-h-[44px] md:min-h-8" onClick={() => onPin(group)}>
            Привязать вручную
          </Button>
        )}
      </div>
    );
  }

  if (group.placement !== 'manual') return null;

  return (
    <div className="flex flex-col items-start gap-[var(--s-2)] px-[var(--s-4)] pb-[var(--s-2)]">
      <p className="text-xs text-muted [overflow-wrap:anywhere]">
        {MANUAL_PLACEMENT_LABEL}
        {message}
      </p>
      {canEdit && group.site_pin_id != null && (
        <Button
          className="min-h-[44px] md:min-h-8"
          onClick={() => {
            revoke.reset();
            setConfirming(true);
          }}
        >
          Снять привязку
        </Button>
      )}
      {confirming && (
        <Dialog
          open
          onClose={() => setConfirming(false)}
          busy={revoke.isPending}
          title="Снять привязку?"
          description={`${group.label} вернётся к посадке по осям и ядрам; если посадить его так нельзя, он станет не поставленным.`}
          footer={
            <DialogActions>
              <Button className="min-h-[44px] md:min-h-8" disabled={revoke.isPending} onClick={() => setConfirming(false)}>
                Отмена
              </Button>
              <Button
                variant="primary"
                className="min-h-[44px] md:min-h-8"
                disabled={revoke.isPending}
                onClick={() => {
                  if (group.site_pin_id == null) return;
                  revoke.mutate(group.site_pin_id, { onSuccess: () => setConfirming(false) });
                }}
              >
                Снять привязку
              </Button>
            </DialogActions>
          }
        >
          {revoke.isError && (
            <p role="alert" className="text-sm text-danger [overflow-wrap:anywhere]">
              {cadErrorText(revoke.error)}
            </p>
          )}
        </Dialog>
      )}
    </div>
  );
};
