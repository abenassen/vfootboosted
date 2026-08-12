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

/** Chiude le notifiche che il test ha appena verificato.
 *
 *  Queste prove girano in Chrome VERO (il guscio headless non ha il dominio DevTools
 *  del service worker), quindi `showNotification` produce una notifica di sistema che
 *  resta nel centro notifiche di chi lancia i test. Il 12/08/2026 sono state
 *  segnalate come un difetto dell'app da chi se le e' trovate sul desktop: due
 *  esecuzioni della suite, due «Ruolo di D. Berardi» e due payload illeggibili. Il
 *  test non cambia quello che verifica -- la notifica c'e' e la si legge -- ma non
 *  deve lasciare tracce dietro di se'. */
async function chiudiNotifiche(page: import('@playwright/test').Page): Promise<void> {
  await page.evaluate(async () => {
    const r = await navigator.serviceWorker.ready;
    for (const n of await r.getNotifications()) n.close();
  });
}

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

  test('il service worker si registra e diventa attivo', async ({ page }) => {
    await page.goto('/');
    // `ready` resolves as soon as a registration HAS an active worker, which can
    // still be in `activating` for a moment — polling here rather than asserting
    // on the instant avoids a race that is in the test, not in the app.
    await expect
      .poll(
        () =>
          page.evaluate(async () => {
            const reg = await navigator.serviceWorker.ready;
            return reg.active?.state ?? null;
          }),
        { timeout: 10_000 },
      )
      .toBe('activated');

    const scope = await page.evaluate(async () => (await navigator.serviceWorker.ready).scope);
    // Scope must be the origin root: a worker registered from a subpath would
    // only ever see part of the app.
    expect(scope).toBe(ORIGIN.replace(/\/$/, '') + '/');
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
    await chiudiNotifiche(page);
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
      // Si dichiara una prova: il fallback mostra il testo GREZZO nel corpo, e
      // questa notifica finisce davvero nel centro notifiche di chi lancia i test
      // (serve Chrome vero, v. playwright.config). Un payload che diceva solo
      // "questo non è json" è stato segnalato come un difetto dell'app, il
      // 12/08/2026, da chi l'aveva vista comparire.
      data: 'prova end-to-end: payload non JSON, atteso',
    });

    const shown = await page.waitForFunction(async () => {
      const r = await navigator.serviceWorker.ready;
      const ns = await r.getNotifications();
      return ns.length ? ns.map((n) => n.title) : null;
    });
    expect((await shown.jsonValue()) as string[]).toEqual(['Vfoot Boosted']);
    await chiudiNotifiche(page);
  });
});

test.describe('@pwa inviti in Home', () => {
  /** Home carries two DIFFERENT invitations, and which of the two appears is the
   *  decision this block exists to hold still (see SetupBanner): on iPhone
   *  installing is the only road to notifications, so the install invite comes
   *  first; everywhere else push works from the browser tab, so proposing an
   *  installation would ask for a step nobody needs while staying silent about the
   *  one that matters.
   *
   *  NOT covered here: the notifications face. It only appears when the server has
   *  VAPID keys, and the mock provider answers `enabled: false` on purpose ("le
   *  notifiche push richiedono il backend reale"), so under the mock there is
   *  nothing to show it with. That face is exercised against a dev server that has
   *  keys — vfoot-sim generates its own; see docs/PWA_TESTING.md.
   *
   *  Signed in through the MOCK provider (`?api=mock`, same trick as the GUI smoke
   *  test): Home is behind auth, and borrowing the real backend would make a
   *  front-end test depend on a database.
   */

  /** Seeds the mock provider's session directly instead of driving the sign-up
   *  form: registering no longer signs you in (the mock mirrors the real
   *  "confirm your email" flow), and this test is about the banner, not about
   *  authentication. */
  async function signInMock(page: import('@playwright/test').Page) {
    await page.goto('/?api=mock');
    await page.evaluate(() =>
      localStorage.setItem(
        'vfoot_mock_session',
        JSON.stringify({ id: 1, username: 'tester', email: 'tester@example.com', avatar: '' }),
      ),
    );
    await page.goto('/home?api=mock');
    await expect(page).toHaveURL(/\/home/);
  }

  /** Located by the close button's accessible name, not by the marketing copy:
   *  the wording is meant to be tuned, and a test that breaks on a comma teaches
   *  people to stop reading failures. Each face carries its own name (see Frame in
   *  SetupBanner), so "which invitation is this" is a question the DOM answers. */
  const installInvite = (page: import('@playwright/test').Page) =>
    page.getByRole('button', { name: "Chiudi l'invito a installare" });

  /** Home has really rendered. An "invito assente" assertion would otherwise pass
   *  just as well on a page that failed to render at all, which is the wrong green:
   *  absence only means something once there is something for it to be absent from. */
  const homeLoaded = (page: import('@playwright/test').Page) =>
    page.getByText('Benvenuto in Vfoot Boosted');

  test("su iPhone l'invito spiega i passaggi, e la chiusura si ricorda", async ({ browser }) => {
    // Safari has no install prompt at all, so the steps ARE the feature. Emulating
    // the user agent exercises our branch; it says nothing about whether push works
    // on a real iPhone, which needs a real iPhone.
    const ctx = await browser.newContext({
      userAgent:
        'Mozilla/5.0 (iPhone; CPU iPhone OS 17_4 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Mobile/15E148 Safari/604.1',
      viewport: { width: 390, height: 844 },
    });
    const page = await ctx.newPage();
    await signInMock(page);

    await expect(installInvite(page)).toBeVisible();
    // A button here would be a promise we cannot keep: there is no prompt to replay.
    await expect(page.getByRole('button', { name: 'Installa', exact: true })).toHaveCount(0);
    await page.getByRole('button', { name: 'Come si fa su iPhone' }).click();
    await expect(page.getByText('\u00abAggiungi alla schermata Home\u00bb')).toBeVisible();

    await installInvite(page).click();
    await expect(installInvite(page)).toHaveCount(0);

    // Remembered: an invitation that returns every visit is an advert.
    await page.goto('/home?api=mock');
    await expect(homeLoaded(page)).toBeVisible();
    await expect(installInvite(page)).toHaveCount(0);
    expect(await page.evaluate(() => localStorage.getItem('vfoot_install_banner_dismissed'))).toBe(
      '1',
    );
    await ctx.close();
  });

  test("fuori da iOS l'installazione non viene proposta in Home", async ({ page }) => {
    // Tested because it is a REMOVAL, and removals come back by accident. Where push
    // works from the tab, Home asks for the permission and for nothing else; the
    // installation stays in Profilo, as the convenience it is.
    await signInMock(page);
    await expect(homeLoaded(page)).toBeVisible();
    await expect(installInvite(page)).toHaveCount(0);
  });

  test("installata, l'invito a installare non compare", async ({ browser }) => {
    const ctx = await browser.newContext({ viewport: { width: 390, height: 844 } });
    const page = await ctx.newPage();
    // display-mode: standalone is how the app knows it was launched from the icon;
    // asking someone to install what they already installed is the clearest way to
    // look broken.
    await page.addInitScript(() => {
      const real = window.matchMedia.bind(window);
      window.matchMedia = ((q: string) =>
        q.includes('display-mode: standalone')
          ? { matches: true, media: q, onchange: null, addEventListener() {}, removeEventListener() {}, addListener() {}, removeListener() {}, dispatchEvent: () => false }
          : real(q)) as typeof window.matchMedia;
    });
    await signInMock(page);
    await expect(installInvite(page)).toHaveCount(0);
    await ctx.close();
  });
});
