import { cx } from '@/components/ui';

/**
 * Ярлычок выкаченной версии: короткий sha коммита, из которого собран портал.
 *
 * Нужен, чтобы после выкладки сразу видеть, что вкладка работает на нужной сборке, а не
 * на закэшированной старой. Версию вшивает сборка образа (`NEXT_PUBLIC_BUILD_VERSION`,
 * deploy/ship-local.sh); локально её нет — тогда ярлычок честно пишет «dev».
 *
 * На десктопе он стоит внизу рейки под меню аккаунта: поверх рабочей области он закрыл бы
 * строку состояния. На телефоне рейки нет — ярлычок висит над нижней навигацией и не
 * перехватывает нажатия.
 */

const SHA_PATTERN = /^[0-9a-f]{7,40}$/i;

export const shortBuildVersion = (raw: string | undefined): string => {
  const version = raw?.trim() ?? '';
  if (version === '') return 'dev';
  return SHA_PATTERN.test(version) ? version.slice(0, 7).toLowerCase() : version;
};

interface IBuildBadgeProps {
  placement: 'rail' | 'floating';
}

export const BuildBadge = ({ placement }: IBuildBadgeProps) => {
  const full = process.env.NEXT_PUBLIC_BUILD_VERSION?.trim() || 'dev';
  const short = shortBuildVersion(full);
  const title = full === 'dev' ? 'Локальная сборка' : `Выкачен коммит ${full}`;

  if (placement === 'rail') {
    return (
      <p
        title={title}
        className="mt-[var(--s-3)] text-center font-mono text-micro leading-tight text-muted select-all"
      >
        {short}
        <br />
        <span className="font-sans">выкачен</span>
      </p>
    );
  }

  return (
    <p
      title={title}
      className={cx(
        'pointer-events-none fixed left-[var(--s-4)] z-20 md:hidden',
        'bottom-[calc(var(--h-bottom-nav)+var(--s-3)+var(--safe-b))]',
        'rounded-[var(--radius-xs)] border border-border bg-surface/85 px-[var(--s-3)] py-[var(--s-1)]',
        'text-micro text-muted',
      )}
    >
      <span className="font-mono">{short}</span> выкачен
    </p>
  );
};
