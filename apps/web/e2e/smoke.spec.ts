import { expect, test } from '@playwright/test';

test('корень портала ведёт на список проектов', async ({ page }) => {
  await page.goto('/');

  await expect(page).toHaveURL(/\/projects$/);
  await expect(page.getByRole('heading', { name: 'Проекты', level: 1 })).toBeVisible();
});

test('страница проектов не скроллится по горизонтали', async ({ page }) => {
  await page.goto('/projects');

  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});
