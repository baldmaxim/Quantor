import { expect, test, type BrowserContext } from '@playwright/test';

/**
 * Оболочка контура управления: навигация, честность панели и изоляция бандла.
 */

const asAdmin = async (context: BrowserContext): Promise<void> => {
  await context.addCookies([
    { name: 'quantor_session', value: 'admin', domain: '127.0.0.1', path: '/' },
  ]);
};

test.beforeEach(async ({ context }) => {
  await asAdmin(context);
});

test('все десять разделов доступны', async ({ page }) => {
  await page.goto('/dashboard');
  const nav = page.getByRole('navigation', { name: 'Разделы управления' });

  const sections = [
    'Обзор',
    'Пространства',
    'Пользователи и доступ',
    'Настройки',
    'Флаги возможностей',
    'Интеграции',
    'Провайдеры моделей',
    'Задания и воркеры',
    'Состояние системы',
    'Журнал',
  ];
  for (const label of sections) {
    await expect(nav.getByRole('link', { name: new RegExp(label) })).toBeVisible();
  }
});

test('переход между разделами работает', async ({ page }) => {
  await page.goto('/dashboard');
  const nav = page.getByRole('navigation', { name: 'Разделы управления' });

  await nav.getByRole('link', { name: /Флаги возможностей/ }).click();
  await expect(page).toHaveURL(/\/feature-flags/);
  await expect(page.getByRole('heading', { name: 'Флаги возможностей' })).toBeVisible();

  await nav.getByRole('link', { name: /Журнал/ }).click();
  await expect(page).toHaveURL(/\/audit/);
});

test('незавершённую возможность включить нельзя', async ({ page }) => {
  await page.goto('/feature-flags');

  // «Просмотрщик» готов — кнопка активна; «Автоматический подсчёт» нет — заблокирована.
  const rows = page.locator('.admin-table tbody tr');
  await expect(
    rows.filter({ hasText: 'Просмотрщик' }).getByRole('button', { name: 'Выключить' }),
  ).toBeEnabled();
  await expect(
    rows.filter({ hasText: 'Автоматический подсчёт' }).getByRole('button', { name: 'Включить' }),
  ).toBeDisabled();
});

test('панель не выдаёт неизмеренное за ноль', async ({ page }) => {
  await page.goto('/dashboard');

  const worker = page.locator('div', { hasText: 'Воркер заданий' }).last();
  await expect(worker).toContainText('не измеряется');
  // Ноль здесь читался бы как «всё хорошо».
  await expect(worker).not.toContainText(/\b0\b/);
});

test('панель не опрашивает сервер сама', async ({ page }) => {
  await page.goto('/dashboard');
  await page.waitForLoadState('networkidle');

  let requests = 0;
  page.on('request', (request) => {
    if (request.url().includes('/api/v1/')) requests += 1;
  });

  await page.waitForTimeout(6000);
  expect(requests, 'обновление должно быть по кнопке, а не по таймеру').toBe(0);
});

test('в бандле админки нет просмотрщика', async ({ page }) => {
  const scripts: string[] = [];
  page.on('response', (response) => {
    if (response.url().endsWith('.js')) scripts.push(response.url());
  });

  await page.goto('/dashboard');
  await page.waitForLoadState('networkidle');
  expect(scripts.length).toBeGreaterThan(0);

  for (const url of scripts) {
    const body = await (await page.request.get(url)).text();
    expect(body, `${url} содержит код просмотрщика`).not.toContain('PDFDocumentProxy');
  }
});

test('секрет интеграции не показывается', async ({ page }) => {
  await page.goto('/integrations');
  await expect(page.getByRole('heading', { name: 'TenderHUB' })).toBeVisible();

  const text = await page.locator('body').innerText();
  expect(text).not.toContain('thk_');
  await expect(page.getByText('Значение не показывается и не логируется')).toBeVisible();
});
