import { EmptyState } from '@quantor/ui';

/**
 * Раздел, которого пока нет.
 *
 * Показывается честно: что здесь появится и почему сейчас пусто. Нарисовать таблицу
 * с выдуманными строками было бы хуже — по контуру управления принимают решения, и
 * правдоподобная пустышка обходится дороже пустого места.
 */
export const Planned = ({
  title,
  willShow,
  stage,
}: {
  title: string;
  willShow: readonly string[];
  stage: string;
}) => (
  <EmptyState
    title={title}
    description={
      <span className="flex flex-col gap-[var(--s-4)]">
        <span>Здесь появится:</span>
        <span className="flex flex-col gap-[var(--s-2)] text-left">
          {willShow.map((item) => (
            <span key={item}>· {item}</span>
          ))}
        </span>
        <span className="text-micro tracking-[0.06em] uppercase">{stage}</span>
      </span>
    }
  />
);
