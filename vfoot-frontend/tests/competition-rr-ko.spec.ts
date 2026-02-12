import { expect, test } from '@playwright/test';
import { mkdir } from 'node:fs/promises';

const SHOT_DIR = 'test-results/gui-rr-ko';

async function snap(page: import('@playwright/test').Page, name: string) {
  await mkdir(SHOT_DIR, { recursive: true });
  await page.screenshot({ path: `${SHOT_DIR}/${name}.png`, fullPage: true });
}

test('backend RR + KO complete flow with screenshots @backend', async ({ page }) => {
  test.skip(process.env.VFOOT_RUN_BACKEND_E2E !== '1', 'Set VFOOT_RUN_BACKEND_E2E=1');

  const username = process.env.VFOOT_E2E_ADMIN_USERNAME || 'smoke_b';
  const password = process.env.VFOOT_E2E_ADMIN_PASSWORD || 'pass12345';
  const stamp = Date.now();
  const rrName = `RR Test ${stamp}`;
  const koName = `KO Test ${stamp}`;

  await page.goto('/?api=backend');
  await page.getByPlaceholder('nomeutente').fill(username);
  await page.locator('input[type="password"]').first().fill(password);
  await page.getByRole('button', { name: 'Accedi' }).click();
  await expect(page).toHaveURL(/\/home\/?$/);
  await snap(page, '01-home');

  await page.getByRole('link', { name: /Admin/ }).click();
  await expect(page).toHaveURL(/\/league-admin(\?.*)?$/);
  await page.getByRole('button', { name: 'League Admin', exact: true }).click();
  await page.getByRole('button', { name: 'Competizioni' }).click();
  await snap(page, '02-competitions-empty-start');

  const competitionSelect = page.locator('select').filter({ has: page.locator('option', { hasText: '+ Nuova competizione' }) }).first();
  await competitionSelect.selectOption({ value: '__new__' });

  await page.getByPlaceholder('Nome competizione (es. Champions League Lega)').fill(rrName);
  await page.locator('select').filter({ hasText: 'Nessun macro: crea solo contenitore' }).first().selectOption('round_robin');
  await page.getByRole('button', { name: 'Crea competizione' }).click();
  await expect(page.getByText(/Competizione creata con macro round_robin/)).toBeVisible();
  await snap(page, '03-round-robin-created');

  await expect(page.locator('span').filter({ hasText: /#1 Regular season/i }).first()).toBeVisible();
  await expect(page.locator('div').filter({ hasText: /Fixture:/i }).first()).toBeVisible();
  await snap(page, '04-round-robin-stage-graph');

  await competitionSelect.selectOption({ value: '__new__' });
  await page.getByPlaceholder('Nome competizione (es. Champions League Lega)').fill(koName);
  await page.locator('select').filter({ hasText: 'Nessun macro: crea solo contenitore' }).first().selectOption('knockout');
  await page.getByRole('button', { name: 'Crea competizione' }).click();
  await expect(page.getByText(/Competizione creata con macro knockout/)).toBeVisible();
  await snap(page, '05-knockout-created');

  await expect(page.locator('span').filter({ hasText: /#1 Play-in/i }).first()).toBeVisible();
  await expect(page.locator('span').filter({ hasText: /#2 Semifinal/i }).first()).toBeVisible();
  await snap(page, '06-knockout-stage-graph');

  await page.getByRole('button', { name: 'Derivata' }).click();
  await expect(page.getByText(/Regole derivate correnti/i)).toBeVisible();
  await snap(page, '07-stage-derived-ui');
});
