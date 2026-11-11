import type { SheetPassportOut } from '@quantor/api-client';
import type { FC } from 'react';

import { Button, StatusBadge, cx } from '@/components/ui';
import {
  STATUS_LABELS,
  STATUS_TONES,
  cellText,
  levelsText,
  sheetKindLabel,
} from '@/lib/consistency/sheet-passports';

import { SheetPassportCell } from './SheetPassportCell';

interface IRowProps {
  readonly row: SheetPassportOut;
  readonly selected: boolean;
  readonly onToggle: (id: string) => void;
  readonly onEdit: (row: SheetPassportOut) => void;
}

export const SheetPassportRow: FC<IRowProps> = ({ row, selected, onToggle, onEdit }) => {
  const label = `${row.file_name}, стр. ${row.page_index + 1}`;
  const elevation = row.elevation_m === null ? null : String(row.elevation_m);

  return (
    <tr
      data-testid="passport-row"
      className={cx('border-b border-border last:border-b-0', selected && 'bg-accent-soft')}
    >
      <td className="px-[var(--s-4)] py-[var(--s-3)] align-top">
        <label className="grid h-[28px] w-[28px] cursor-pointer place-items-center max-md:h-[44px] max-md:w-[44px]">
          <input
            type="checkbox"
            checked={selected}
            aria-label={`Выбрать: ${label}`}
            onChange={() => onToggle(row.id)}
            className="h-[16px] w-[16px] accent-[var(--accent)]"
          />
        </label>
      </td>
      <td className="max-w-[16rem] px-[var(--s-4)] py-[var(--s-3)] align-top text-sm [overflow-wrap:anywhere]">
        {row.file_name}
      </td>
      <td className="tabular px-[var(--s-4)] py-[var(--s-3)] align-top text-sm">
        {row.page_index + 1}
      </td>
      <SheetPassportCell row={row} field="section_mark" text={cellText(row.section_mark)} />
      <SheetPassportCell row={row} field="sheet_kind" text={sheetKindLabel(row.sheet_kind)} />
      <SheetPassportCell row={row} field="stage" text={cellText(row.stage)} />
      <SheetPassportCell row={row} field="building" text={cellText(row.building)} />
      <SheetPassportCell row={row} field="section" text={cellText(row.section)} />
      <SheetPassportCell
        row={row}
        field="level_from"
        text={levelsText(row.level_from, row.level_to)}
      />
      <SheetPassportCell row={row} field="elevation_m" text={cellText(elevation)} />
      <SheetPassportCell row={row} field="code" text={cellText(row.code)} />
      <SheetPassportCell row={row} field="sheet_number" text={cellText(row.sheet_number)} />
      <SheetPassportCell
        row={row}
        field="title"
        text={cellText(row.title)}
        className="min-w-[14rem]"
      />
      <td className="px-[var(--s-4)] py-[var(--s-3)] align-top">
        <StatusBadge tone={STATUS_TONES[row.status]}>{STATUS_LABELS[row.status]}</StatusBadge>
      </td>
      <td className="px-[var(--s-4)] py-[var(--s-3)] align-top">
        <Button compact onClick={() => onEdit(row)} aria-label={`Править: ${label}`}>
          Править
        </Button>
      </td>
    </tr>
  );
};
