import type { Page } from '@playwright/test';
import { expect, test } from '@playwright/test';

async function registerFromLanding(page: Page, username: string, password: string) {
  await page.getByRole('button', { name: 'Registrati' }).click();
  await page.getByPlaceholder('nomeutente').fill(username);
  await page.getByPlaceholder('tu@email.com').fill(`${username}@example.com`);
  await page.locator('input[type="password"]').nth(0).fill(password);
  await page.locator('input[type="password"]').nth(1).fill(password);
  await page.getByRole('button', { name: 'Crea account' }).click();
  await expect(page).toHaveURL(/\/home/);
}

test('mock provider GUI smoke @mock', async ({ page }) => {
  const stamp = Date.now();
  const username = `gui_mock_${stamp}`;
  const password = 'VfootTest!234';

  await page.goto('/?api=mock');
  await registerFromLanding(page, username, password);

  await page.getByRole('link', { name: /Admin/ }).click();
  await expect(page).toHaveURL(/\/league-admin/);

  await page.getByPlaceholder('Nome lega').fill(`Mock League ${stamp}`);
  await page.getByPlaceholder('Nome tua squadra').fill('Mock Team');
  await page.getByRole('button', { name: 'Crea' }).first().click();

  await expect(page.getByText('Lega creata. Invite code:', { exact: false })).toBeVisible();
});

test('backend provider GUI smoke @backend', async ({ page }) => {
  test.skip(process.env.VFOOT_RUN_BACKEND_E2E !== '1', 'Set VFOOT_RUN_BACKEND_E2E=1 and run backend on http://127.0.0.1:8000.');

  const stamp = Date.now();
  const username = `gui_backend_${stamp}`;
  const password = 'VfootTest!234';

  await page.goto('/?api=backend');
  await registerFromLanding(page, username, password);

  await page.getByRole('link', { name: /Admin/ }).click();
  await expect(page).toHaveURL(/\/league-admin/);

  await page.getByPlaceholder('Nome lega').fill(`Backend League ${stamp}`);
  await page.getByPlaceholder('Nome tua squadra').fill('Backend Team');
  await page.getByRole('button', { name: 'Crea' }).first().click();

  await expect(page.getByText('Invite code:', { exact: false })).toBeVisible();
});
