import { expect, test } from '@playwright/test';

/** Automated PWA checks, on the laptop, with no phone involved.
 *
 *  What this can and cannot prove is worth stating, because the temptation is to
 *  believe a green run means "notifications work for everyone":
 *
 *  CAN — the manifest is served and coherent; the service worker registers and
 *  activates; the precache holds the shell and NOT the API; a push delivered to
 *  the worker produces the notification we intended, with the right title, body
 *  and click target. The push here is injected through the DevTools protocol
 *  (`ServiceWorker.deliverPushMessage`), i.e. the same event a real FCM delivery
 *  produces, minus the network — so the worker's own logic is genuinely covered.
 *
 *  CANNOT — anything about iOS, which has no engine on Linux, and nothing about
 *  Apple's requirement that the app be installed to the Home Screen. Nor the
 *  real VAPID/FCM round trip, which needs a live subscription: that one is
 *  `npm run test:pwa:roundtrip` (see docs/PWA_TESTING.md), kept separate because
 *  it talks to Google.
 *
 *  Runs against the dev server (devOptions.enabled), so `npm run dev` is enough.
 */

const ORIGIN = process.env.VFOOT_E2E_BASE_URL || 'http://127.0.0.1:5173';

test.describe('@pwa PWA', () => {
  test('il manifest è servito e dice come installarsi', async ({ request }) => {
    const res = await request.get('/manifest.webmanifest');
    expect(res.ok()).toBeTruthy();
    const m = await res.json();

    expect(m.name).toBe('Vfoot Boosted');
    expect(m.display).toBe('standalone');
    // Without a standalone display and a start_url in scope the browser refuses
    // to treat it as installable at all.
    expect(m.start_url).toBe('/home');
    expect(m.scope).toBe('/');

    const sizes = m.icons.map((i: { sizes: string }) => i.sizes);
    expect(sizes).toContain('192x192');
    expect(sizes).toContain('512x512');
    // Android crops to the launcher shape: without a maskable icon the logo gets
    // clipped on most phones.
    expect(m.icons.some((i: { purpose?: string }) => i.purpose === 'maskable')).toBeTruthy();
  });

  test('le icone dichiarate esistono davvero', async ({ request }) => {
    for (const path of [
      '/icons/icon-192.png',
      '/icons/icon-512.png',
      '/icons/maskable-192.png',
      '/icons/maskable-512.png',
      '/icons/apple-touch-icon.png',
    ]) {
      const res = await request.get(path);
      expect(res.ok(), `${path} manca`).toBeTruthy();
      expect(res.headers()['content-type']).toContain('image/png');
    }
  });

  test('iOS trova apple-touch-icon nella pagina', async ({ page }) => {
    // iOS ignores the manifest icons for the Home Screen; without this tag Safari
    // puts a screenshot of the page under the user's finger.
    await page.goto('/');
    await expect(page.locator('link[rel="apple-touch-icon"]')).toHaveCount(1);
    await expect(page.locator('meta[name="theme-color"]')).toHaveAttribute('content', '#0f172a');
  });

  test('il service worker si registra e prende il controllo', async ({ page }) => {
    await page.goto('/');
    const state = await page.evaluate(async () => {
      const reg = await navigator.serviceWorker.ready;
      return { scope: reg.scope, active: reg.active?.state ?? null };
    });
    expect(state.active).toBe('activated');
    expect(state.scope).toBe(ORIGIN.replace(/\/$/, '') + '/');
  });

  test('una push consegnata al worker diventa una notifica', async ({ page, context }) => {
    await context.grantPermissions(['notifications'], { origin: ORIGIN });
    await page.goto('/');
    await page.evaluate(() => navigator.serviceWorker.ready);

    const cdp = await context.newCDPSession(page);
    const registrations: Array<{ registrationId: string; scopeURL: string }> = [];
    cdp.on('ServiceWorker.workerRegistrationUpdated', (e) =>
      registrations.push(...(e.registrations as typeof registrations)),
    );
    await cdp.send('ServiceWorker.enable');
    await expect
      .poll(() => registrations.find((r) => r.scopeURL.startsWith(ORIGIN)) !== undefined, {
        timeout: 5000,
      })
      .toBeTruthy();
    const reg = registrations.find((r) => r.scopeURL.startsWith(ORIGIN))!;

    await cdp.send('ServiceWorker.deliverPushMessage', {
      origin: ORIGIN,
      registrationId: reg.registrationId,
      data: JSON.stringify({
        title: 'Ti hanno chiesto un parere',
        body: 'Ruolo di D. Berardi',
        url: '/decisioni',
        tag: 'decision-1',
      }),
    });

    const shown = await page.waitForFunction(async () => {
      const r = await navigator.serviceWorker.ready;
      const ns = await r.getNotifications();
      return ns.length
        ? ns.map((n) => ({ title: n.title, body: n.body, tag: n.tag, data: n.data }))
        : null;
    });
    const list = (await shown.jsonValue()) as Array<{
      title: string;
      body: string;
      tag: string;
      data: { url: string };
    }>;
    expect(list).toHaveLength(1);
    expect(list[0].title).toBe('Ti hanno chiesto un parere');
    expect(list[0].body).toBe('Ruolo di D. Berardi');
    // The click target is what takes the user to the question rather than home.
    expect(list[0].data.url).toBe('/decisioni');
    // Per-subject tag: three updates on one decision stay one line in the shade.
    expect(list[0].tag).toBe('decision-1');
  });

  test('una push illeggibile mostra comunque qualcosa', async ({ page, context }) => {
    // A subscription made with userVisibleOnly that shows nothing gets penalised
    // by the browser, so a malformed payload must not end in silence.
    await context.grantPermissions(['notifications'], { origin: ORIGIN });
    await page.goto('/');
    await page.evaluate(() => navigator.serviceWorker.ready);

    const cdp = await context.newCDPSession(page);
    const registrations: Array<{ registrationId: string; scopeURL: string }> = [];
    cdp.on('ServiceWorker.workerRegistrationUpdated', (e) =>
      registrations.push(...(e.registrations as typeof registrations)),
    );
    await cdp.send('ServiceWorker.enable');
    await expect
      .poll(() => registrations.find((r) => r.scopeURL.startsWith(ORIGIN)) !== undefined, {
        timeout: 5000,
      })
      .toBeTruthy();

    await cdp.send('ServiceWorker.deliverPushMessage', {
      origin: ORIGIN,
      registrationId: registrations.find((r) => r.scopeURL.startsWith(ORIGIN))!.registrationId,
      data: 'questo non è json',
    });

    const shown = await page.waitForFunction(async () => {
      const r = await navigator.serviceWorker.ready;
      const ns = await r.getNotifications();
      return ns.length ? ns.map((n) => n.title) : null;
    });
    expect((await shown.jsonValue()) as string[]).toEqual(['Vfoot Boosted']);
  });
});
