import { test, expect } from '@playwright/test';

test('deep link to kid matches works on cold load', async ({ page }) => {
  await page.goto('/kids/1/matches');
  await expect(page.getByRole('heading', { name: /Sam — matches/ })).toBeVisible();
});
