import { expect, test } from '@playwright/test';

/**
 * Телефон.
 *
 * Контур управления десктопный, и притворяться иначе не нужно. Проверяется другое:
 * страница не едет по горизонтали, а таблицы прокручиваются внутри себя.
 */

test.beforeEach(async ({ context }) => {
  await context.addCookies([
    { name: 'quantor_session', value: 'admin', domain: '127.0.0.1', path: '/' },
  ]);
});

test('нет горизонтального скролла страницы', async ({ page }) => {
  await page.goto('/settings');
  await expect(page.getByRole('heading', { name: 'Настройки' })).toBeVisible();

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(
    overflow,
    'таблица должна прокручиваться внутри себя, а не растягивать страницу',
  ).toBeLessThanOrEqual(1);
});

test('разделы доступны через выдвижную панель', async ({ page }) => {
  await page.goto('/dashboard');

  const nav = page.getByRole('navigation', { name: 'Разделы управления' });
  await expect(nav).toBeHidden();

  await page.getByRole('button', { name: 'Разделы' }).click();
  await expect(nav).toBeVisible();
  await expect(nav.getByRole('link', { name: /Журнал/ })).toBeVisible();
});
