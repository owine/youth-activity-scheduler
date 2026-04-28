import { test, expect } from '@playwright/test';

test('inbox shows seeded alert and kid match counts', async ({ page }) => {
  await page.goto('/');
  await expect(page.getByText("What's new this week")).toBeVisible();
  await expect(page.getByText(/Spring T-Ball/)).toBeVisible();
  await expect(page.getByText('Sam')).toBeVisible();
});

test('clicking an alert opens detail drawer', async ({ page }) => {
  await page.goto('/');
  await page.getByText(/Spring T-Ball/).click();
  await expect(page.getByText(/Watchlist hit/)).toBeVisible();
});
