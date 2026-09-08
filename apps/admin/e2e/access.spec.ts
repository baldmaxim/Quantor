import { expect, test, type BrowserContext } from '@playwright/test';

/**
 * Граница входа в контур управления.
 *
 * Проверяется не «редиректит ли», а то, что оболочка **не построена**: её разметки нет
 * в ответе. Клиентская проверка этого дать не может — к моменту её выполнения разметка
 * уже в браузере, а привилегированные запросы уже ушли (ADR-0013).
 */

const setSession = async (context: BrowserContext, value: string): Promise<void> => {
  await context.addCookies([{ name: 'quantor_session', value, domain: '127.0.0.1', path: '/' }]);
};

test('без сеанса оболочка не строится', async ({ page }) => {
  await page.goto('/dashboard');

  await expect(page).toHaveURL(/\/signed-out/);
  await expect(page.getByRole('heading', { name: 'Требуется вход' })).toBeVisible();
  // Навигации по разделам нет в разметке вовсе.
  await expect(page.getByRole('navigation', { name: 'Разделы управления' })).toHaveCount(0);
});

test('вошедший без прав получает отказ, а не оболочку', async ({ page, context }) => {
  await setSession(context, 'engineer');
  await page.goto('/dashboard');

  await expect(page).toHaveURL(/\/forbidden/);
  await expect(page.getByRole('heading', { name: 'Доступ запрещён' })).toBeVisible();
  await expect(page.getByRole('navigation', { name: 'Разделы управления' })).toHaveCount(0);
});

test('администратор платформы видит оболочку', async ({ page, context }) => {
  await setSession(context, 'admin');
  await page.goto('/dashboard');

  await expect(page.getByRole('navigation', { name: 'Разделы управления' })).toBeVisible();
  await expect(page.getByRole('heading', { name: 'Обзор' })).toBeVisible();
});

test('без прав ни один привилегированный запрос не уходит', async ({ page, context }) => {
  await setSession(context, 'engineer');

  const privileged: string[] = [];
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/admin/')) privileged.push(request.url());
  });

  await page.goto('/settings');
  await page.waitForLoadState('networkidle');

  expect(privileged, 'отказ должен наступать до запросов за данными').toEqual([]);
});
