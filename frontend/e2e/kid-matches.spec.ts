import { test, expect } from '@playwright/test';

test('navigate from inbox kid card to matches page', async ({ page }) => {
  await page.goto('/');
  await page.getByText('Sam').first().click();
  await expect(page).toHaveURL(/\/kids\/1\/matches/);
  await expect(page.getByText(/Spring T-Ball/)).toBeVisible();
});
