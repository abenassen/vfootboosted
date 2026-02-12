import type { Page } from '@playwright/test';
import { expect, test } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

const SCREENSHOT_DIR = 'test-results/gui-smoke';
const BACKEND_SHOT_DIR = 'test-results/gui-backend-full';

async function snap(page: Page, name: string) {
  await mkdir(SCREENSHOT_DIR, { recursive: true });
  await page.screenshot({ path: `${SCREENSHOT_DIR}/${name}.png`, fullPage: true });
}

async function snapBackend(page: Page, name: string) {
  await mkdir(BACKEND_SHOT_DIR, { recursive: true });
  await page.screenshot({ path: `${BACKEND_SHOT_DIR}/${name}.png`, fullPage: true });
}

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
  await snap(page, '01-landing');
  await registerFromLanding(page, username, password);
  await snap(page, '02-home-after-register');

  await page.getByRole('link', { name: /Admin/ }).click();
  await expect(page).toHaveURL(/\/league-admin/);
  await snap(page, '03-admin-user-tab');

  await page.getByPlaceholder('Nome lega').fill(`Mock League ${stamp}`);
  await page.getByPlaceholder('Nome tua squadra').fill('Mock Team');
  await page.getByRole('button', { name: 'Crea' }).first().click();

  await expect(page.getByText('Lega creata. Invite code:', { exact: false })).toBeVisible();

  await page.getByRole('button', { name: 'Vai a League Admin' }).click();
  await snap(page, '04-admin-league-overview');

  await page.getByRole('button', { name: 'Roster' }).click();
  await snap(page, '05-admin-league-roster');

  await page.getByRole('button', { name: 'Competizioni' }).click();
  await snap(page, '06-admin-league-competitions');

  await page.getByRole('button', { name: 'Asta' }).click();
  await snap(page, '07-admin-league-auction');
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

test('backend provider GUI comprehensive @backend', async ({ page }) => {
  test.skip(process.env.VFOOT_RUN_BACKEND_E2E !== '1', 'Set VFOOT_RUN_BACKEND_E2E=1 and run backend on http://127.0.0.1:8000.');

  const username = process.env.VFOOT_E2E_USERNAME || 'smoke_a';
  const password = process.env.VFOOT_E2E_PASSWORD || 'pass12345';
  const stamp = Date.now();
  const auctionPlayerIds = process.env.VFOOT_E2E_AUCTION_PLAYER_IDS || '1,2,3,4,5,6';

  await page.goto('/?api=backend');
  await snapBackend(page, '01-landing-login');

  await page.getByPlaceholder('nomeutente').fill(username);
  await page.locator('input[type="password"]').first().fill(password);
  await page.getByRole('button', { name: 'Accedi' }).click();
  await expect(page).toHaveURL(/\/home/);
  await snapBackend(page, '02-home');

  await page.getByRole('link', { name: /Admin/ }).click();
  await expect(page).toHaveURL(/\/league-admin/);
  await snapBackend(page, '03-admin-user-tab');

  await page.getByRole('button', { name: 'League Admin', exact: true }).click();
  await snapBackend(page, '04-league-overview');

  const openMarketButton = page.getByRole('button', { name: 'Apri mercato' });
  if (await openMarketButton.count()) {
    await openMarketButton.click();
  }

  await page.getByRole('button', { name: 'Roster' }).click();
  await expect(page.getByText('Roster Team')).toBeVisible();
  await snapBackend(page, '05-roster-tab');

  await page.getByRole('button', { name: 'Competizioni' }).click();
  await expect(page.getByRole('button', { name: 'Crea competizione' })).toBeVisible();
  await page.getByPlaceholder('Nome competizione').fill(`Backend Cup ${stamp}`);
  await page.getByRole('button', { name: 'Crea competizione' }).click();
  await expect(page.getByText('Competizione creata')).toBeVisible();
  await snapBackend(page, '06-competitions-created');

  await page.getByRole('button', { name: 'Asta' }).click();
  await expect(page.getByText('Auction Room (beta)')).toBeVisible();
  await page.getByPlaceholder("Player IDs per creare l'asta (es. 101,102,103...)").fill(auctionPlayerIds);
  await page.getByRole('button', { name: 'Crea asta' }).click();
  await expect(page.getByText('Asta creata:', { exact: false })).toBeVisible();
  await page.getByRole('button', { name: 'Nominate next' }).click();
  await snapBackend(page, '07-auction-tab-state');
});
