import { render, screen } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';

import { BuildBadge, shortBuildVersion } from './BuildBadge';

/**
 * Ярлычок версии: по нему проверяют, что вкладка работает на только что выкаченной сборке.
 */

const SHA = '205fdfd8c0a1b2c3d4e5f60718293a4b5c6d7e8f';

describe('ярлычок версии', () => {
  afterEach(() => {
    vi.unstubAllEnvs();
  });

  it('сокращает sha до семи знаков', () => {
    expect(shortBuildVersion(SHA)).toBe('205fdfd');
    expect(shortBuildVersion(' 205FDFD ')).toBe('205fdfd');
  });

  it('без версии пишет dev, а не пустоту', () => {
    expect(shortBuildVersion(undefined)).toBe('dev');
    expect(shortBuildVersion('  ')).toBe('dev');
    expect(shortBuildVersion('e2e')).toBe('e2e');
  });

  it('показывает короткий sha и полный в подсказке', () => {
    vi.stubEnv('NEXT_PUBLIC_BUILD_VERSION', SHA);
    render(<BuildBadge placement="rail" />);

    const badge = screen.getByTitle(`Выкачен коммит ${SHA}`);
    expect(badge).toHaveTextContent('205fdfdвыкачен');
  });

  it('на телефоне не перехватывает нажатия', () => {
    vi.stubEnv('NEXT_PUBLIC_BUILD_VERSION', SHA);
    render(<BuildBadge placement="floating" />);

    const badge = screen.getByTitle(`Выкачен коммит ${SHA}`);
    expect(badge).toHaveTextContent('205fdfd выкачен');
    expect(badge.className).toContain('pointer-events-none');
  });
});
