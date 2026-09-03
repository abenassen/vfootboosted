import { expect, test, type Page } from '@playwright/test';

const PLAYER_ROLES = [
  'GK',
  'DEF', 'DEF', 'DEF',
  'MID', 'MID', 'MID', 'MID',
  'ATT', 'ATT', 'ATT',
  'GK', 'DEF', 'MID', 'ATT',
] as const;

function lineupContext() {
  const roster = PLAYER_ROLES.map((role, index) => ({
    player_id: index + 1,
    name: `Giocatore ${index + 1}`,
    price: 10,
    role,
    avg_col: 2,
    footprint: { Z_2_2: 1 },
    appearances: 10,
    starts: 8,
    avg_minutes: 75,
    minutes_label: 'high',
    recent_appearances: 5,
    recent_avg_minutes: 75,
    recent_window: 5,
    form: 6,
    value: 6,
    value_basis: 'misurata',
    starting: null,
    next_match: null,
  }));

  return {
    team: { team_id: 1, name: 'Casa FC', crest: null },
    competitions: [{ competition_id: 1, name: 'Campionato' }],
    competition: 1,
    matchdays: [1],
    matchday: 1,
    as_of_matchday: 1,
    prior_matches: 0,
    zone_grid: { cols: 5, rows: 4, zone_keys: ['Z_0_0'] },
    rules: {
      starters: 11,
      gk_separate_slot: true,
      mode: 'classic',
      classic_constraints: {
        starters: 11,
        per_role: {
          GK: { min: 1, max: 1 },
          DEF: { min: 3, max: 5 },
          MID: { min: 0, max: 6 },
          ATT: { min: 1, max: 3 },
        },
      },
    },
    mode: 'classic',
    roster,
    saved_lineup: {
      gk_player_id: 1,
      starter_player_ids: Array.from({ length: 10 }, (_, index) => index + 2),
      bench_player_ids: [12, 13, 14, 15],
      starter_backups: [],
    },
    lineup_source: { kind: 'saved', from_matchday: null, vacant_roles: [] },
    suggested_lineup: { gk_player_id: 1, starter_player_ids: Array.from({ length: 10 }, (_, index) => index + 2) },
    lineup_lock: {
      mode: 'matchday',
      enforced: false,
      closes_at: null,
      closes_with: null,
      closed: false,
      locked_player_ids: [],
      defence_locked: false,
      roster_frozen_at: null,
      defence_count: null,
    },
  };
}

async function openFormation(page: Page) {
  const context = lineupContext();

  await page.route('**/api/v1/**', async (route) => {
    const path = new URL(route.request().url()).pathname;
    let body: unknown = [];

    if (path.endsWith('/auth/me')) {
      body = { user: { id: 1, username: 'test', email: 'test@example.com', avatar: '' } };
    } else if (path.endsWith('/leagues/1/lineup')) {
      body = context;
    } else if (path.endsWith('/leagues/1/matchdays')) {
      body = [{ is_fieldable: true, real_matchday: 1 }];
    } else if (path.endsWith('/leagues/1/competitions')) {
      body = [{ competition_id: 1, name: 'Campionato' }];
    } else if (path.endsWith('/leagues')) {
      body = [{ league_id: 1, name: 'Lega test', role: 'admin', team_name: 'Casa FC' }];
    } else if (path.endsWith('/news')) {
      body = { items: [] };
    }

    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify(body),
    });
  });

  await page.addInitScript(() => {
    localStorage.setItem('vfoot_auth_token', 'test-token');
    localStorage.setItem('vfoot_selected_league_id', '1');
  });
  await page.goto('/squad/formation?api=backend&competition=1&matchday=1');
  await expect(page.getByText('Formazione · Casa FC', { exact: true })).toBeVisible();
}

test('allows starting a formation from an empty pitch', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 900 });
  await openFormation(page);

  const clearButton = page.getByRole('button', { name: 'Svuota titolari', exact: true });
  await expect(clearButton).toHaveCount(1);
  await clearButton.click();

  await expect(page.getByText('Titolari 0/11', { exact: true })).toBeVisible();
  await expect(page.getByText('3-4-3', { exact: true })).toHaveCount(2);
  await expect(page.getByText('Manca un portiere', { exact: true })).toBeVisible();
  await expect(page.getByRole('list').getByText('Servono esattamente 11 titolari (ne hai 0).', { exact: true })).toBeVisible();
  await expect(page.getByRole('button', { name: 'Titolare', exact: true })).toHaveCount(15);
});

test('keeps the clear action usable on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await openFormation(page);

  const clearButton = page.getByRole('button', { name: 'Svuota', exact: true });
  await expect(clearButton).toHaveCount(1);
  await clearButton.click();

  await expect(page.getByText('0/11', { exact: true })).toBeVisible();
  const overflow = await page.evaluate(() => {
    const scrolling = document.scrollingElement;
    return scrolling ? scrolling.scrollWidth - scrolling.clientWidth : 0;
  });
  expect(overflow).toBeLessThanOrEqual(1);
});
