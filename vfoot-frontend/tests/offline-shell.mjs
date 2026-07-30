/**
 * Does the app still open with no connection?
 *
 *   npm run test:pwa:offline        (builds, then runs this)
 *
 * Separate from the Playwright suite because it needs the PRODUCTION build: the
 * dev server serves a different worker with a different precache, so a green dev
 * run says nothing about what users get.
 *
 * The case that matters is `/home`, the manifest's `start_url` — what the
 * INSTALLED APP OPENS. Precaching alone does not cover it: the precache answers
 * for the exact URLs in it, so `/` worked while every client-side route died on
 * the browser's offline page. It takes a NavigationRoute bound to the shell, and
 * this is the test that would have caught its absence.
 */
import { chromium } from 'playwright';
import { spawn } from 'node:child_process';
import { mkdtempSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const PORT = 4179;
const ORIGIN = `http://127.0.0.1:${PORT}`;
// A client-side route, a deep link, and the start_url — plus one path that must
// NOT be answered by the shell, or a typed /admin/ would show the SPA offline.
const SHELL_PATHS = ['/', '/home', '/decisioni', '/profilo'];

const preview = spawn(
  'npx',
  ['vite', 'preview', '--port', String(PORT), '--strictPort'],
  { stdio: 'ignore' },
);
const work = mkdtempSync(join(tmpdir(), 'vfoot-offline-'));
let failures = 0;

const done = (code) => {
  preview.kill();
  rmSync(work, { recursive: true, force: true });
  process.exit(code);
};

try {
  // Wait for the preview server rather than sleeping a guessed amount.
  for (let i = 0; ; i++) {
    try {
      await fetch(ORIGIN + '/');
      break;
    } catch {
      if (i > 40) {
        console.error('✗ vite preview non è partito');
        done(1);
      }
      await new Promise((r) => setTimeout(r, 250));
    }
  }

  const ctx = await chromium.launchPersistentContext(join(work, 'profile'), {
    headless: true,
    channel: 'chrome',
  });
  const page = await ctx.newPage();
  await page.goto(ORIGIN + '/home');
  await page.evaluate(() => navigator.serviceWorker.ready);
  // The precache runs on install; going offline before it finishes would test
  // the wrong thing.
  await page.waitForFunction(
    async () => (await caches.keys()).some((k) => k.includes('precache')),
    null,
    { timeout: 15000 },
  );
  console.log('worker attivo e shell in cache');

  await ctx.setOffline(true);
  for (const path of SHELL_PATHS) {
    try {
      const res = await page.goto(ORIGIN + path, { timeout: 8000 });
      const ok = res?.status() === 200 && (await page.locator('#root').count()) === 1;
      console.log(`  ${ok ? '✓' : '✗'} offline ${path} → HTTP ${res?.status()}`);
      if (!ok) failures++;
    } catch (e) {
      console.log(`  ✗ offline ${path} → ${String(e).split('\n')[0].slice(0, 60)}`);
      failures++;
    }
  }

  // The backend must never be impersonated by the shell.
  const api = await page.evaluate(async (o) => {
    try {
      const r = await fetch(o + '/api/v1/push/config');
      return `${r.status} ${(await r.text()).slice(0, 20)}`;
    } catch (e) {
      return `errore di rete: ${String(e).slice(0, 40)}`;
    }
  }, ORIGIN);
  const apiOk = api.startsWith('errore di rete');
  console.log(`  ${apiOk ? '✓' : '✗'} offline /api/… non viene servito dalla cache (${api})`);
  if (!apiOk) failures++;

  await ctx.close();
} catch (e) {
  console.error('✗', e);
  done(1);
}

console.log(
  failures ? `\n✗ ${failures} controlli falliti` : '\n✓ La shell si apre offline su ogni rotta.',
);
done(failures ? 1 : 0);
