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

test('панель показывает числа сервера, а не выдуманные', async ({ page }) => {
  await page.goto('/dashboard');

  // Пульс исполнителей стал измеримым вместе с выносом заданий в отдельный процесс,
  // и панель обязана показывать ровно то, что ответил сервер, — ни больше ни меньше.
  const workers = page.locator('div', { hasText: 'Исполнители заданий' }).last();
  await expect(workers).toContainText('1 из 1');

  const failures = page.locator('div', { hasText: 'Отказы заданий за сутки' }).last();
  await expect(failures).toContainText('2');
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

test('битый архив нельзя повторить', async ({ page }) => {
  await page.goto('/jobs');

  const row = page.locator('.admin-table tbody tr').filter({ hasText: 'ARCHIVE_UNSAFE_PATH' });
  await expect(row.getByRole('button', { name: 'Повторить' })).toBeDisabled();
  // Отмена доступна только тому, что ещё не начали.
  await expect(row.getByRole('button', { name: 'Отменить' })).toBeDisabled();
});

test('состояние показывает, что исполнителя не запускали, и как это починить', async ({ page }) => {
  await page.goto('/health');

  await expect(page.getByText('исполнитель ни разу не запускался')).toBeVisible();
  await expect(page.getByText('pnpm dev:worker')).toBeVisible();
  // Ненастроенное не выдаётся за исправное.
  await expect(page.getByText('не настроено').first()).toBeVisible();
});

test('страница состояния не опрашивает сервер сама', async ({ page }) => {
  await page.goto('/health');
  await page.waitForLoadState('networkidle');

  let requests = 0;
  page.on('request', (request) => {
    if (request.url().includes('/diagnostics')) requests += 1;
  });

  await page.waitForTimeout(6000);
  expect(requests, 'обновление только по кнопке').toBe(0);

  await page.getByRole('button', { name: 'Проверить снова' }).click();
  await expect.poll(() => requests).toBe(1);
});

test('реестр моделей честно сообщает, что поставщиков нет', async ({ page }) => {
  await page.goto('/model-providers');

  await expect(page.getByText('Поставщики не описаны')).toBeVisible();
  await expect(page.getByText('MODEL_PROVIDERS')).toBeVisible();
  // Ни одного обращения к моделям при открытии — и никакой выдуманной таблицы.
  await expect(page.locator('.admin-table')).toHaveCount(0);
});
