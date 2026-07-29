/**
 * The full Web Push round trip, on the laptop, for real.
 *
 *   npm run test:pwa:roundtrip
 *
 * Kept OUT of the Playwright suite on purpose: this one leaves the machine. It
 * subscribes a real Chrome to Google's push service, sends an encrypted payload
 * to that endpoint with pywebpush and a throwaway VAPID pair, and waits for our
 * service worker to show the notification. So it exercises the parts the offline
 * suite cannot: the VAPID signature, the RFC 8291 encryption, FCM, and the wake
 * of a worker from cold.
 *
 * What it needs: the dev server running (`npm run dev`), network access, and the
 * backend venv for pywebpush. It does NOT need the backend running, nor its
 * keys — the pair is generated here and thrown away, which is also what makes it
 * safe to run against production credentials by accident: there are none.
 *
 * If this passes and a phone still gets nothing, the problem is not the code.
 */
import { chromium } from 'playwright';
import { execFileSync } from 'node:child_process';
import { mkdtempSync, writeFileSync, rmSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const ORIGIN = process.env.VFOOT_E2E_BASE_URL || 'http://127.0.0.1:5173';
const PYTHON = process.env.VFOOT_PYTHON || '../vfoot-backend/.venv/bin/python';
const work = mkdtempSync(join(tmpdir(), 'vfoot-push-'));
const fail = (msg) => {
  console.error(`\n✗ ${msg}`);
  rmSync(work, { recursive: true, force: true });
  process.exit(1);
};

// 1. A throwaway VAPID pair. Same shape as `manage.py vapid_keys`.
writeFileSync(
  join(work, 'gen.py'),
  `
import base64, json
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
k = ec.generate_private_key(ec.SECP256R1())
pub = k.public_key().public_bytes(serialization.Encoding.X962,
                                  serialization.PublicFormat.UncompressedPoint)
b = lambda x: base64.urlsafe_b64encode(x).decode().rstrip("=")
print(json.dumps({"public": b(pub),
                  "private": b(k.private_numbers().private_value.to_bytes(32, "big"))}))
`,
);
const vapid = JSON.parse(execFileSync(PYTHON, [join(work, 'gen.py')], { encoding: 'utf8' }));
console.log('1/4  coppia VAPID generata (usa e getta)');

// 2. Real Chrome, real subscription.
const ctx = await chromium.launchPersistentContext(join(work, 'profile'), {
  headless: true,
  channel: 'chrome',
});
await ctx.grantPermissions(['notifications'], { origin: ORIGIN });
const page = await ctx.newPage();
try {
  await page.goto(ORIGIN, { timeout: 15000 });
} catch {
  await ctx.close();
  fail(`${ORIGIN} non risponde: serve \`npm run dev\` in un altro terminale.`);
}
await page.evaluate(() => navigator.serviceWorker.ready);

const sub = await page.evaluate(async (key) => {
  const padded = key.padEnd(key.length + ((4 - (key.length % 4)) % 4), '=');
  const raw = atob(padded.replace(/-/g, '+').replace(/_/g, '/'));
  const bytes = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) bytes[i] = raw.charCodeAt(i);
  const reg = await navigator.serviceWorker.ready;
  const s = await reg.pushManager.subscribe({
    userVisibleOnly: true,
    applicationServerKey: bytes,
  });
  return s.toJSON();
}, vapid.public);
const service = new URL(sub.endpoint).host;
console.log(`2/4  iscritto al servizio push reale (${service})`);

// 3. Send from the outside, exactly as Django does.
writeFileSync(join(work, 'sub.json'), JSON.stringify(sub));
writeFileSync(join(work, 'vapid.json'), JSON.stringify(vapid));
writeFileSync(
  join(work, 'send.py'),
  `
import json, sys
from pywebpush import webpush, WebPushException
sub = json.load(open(sys.argv[1])); v = json.load(open(sys.argv[2]))
try:
    r = webpush(subscription_info=sub,
                data=json.dumps({"title": "Ti hanno chiesto un parere",
                                 "body": "Ruolo di D. Berardi",
                                 "url": "/decisioni", "tag": "decision-roundtrip"}),
                vapid_private_key=v["private"],
                vapid_claims={"sub": "mailto:no-reply@vfoot.it"}, ttl=60)
    print(r.status_code)
except WebPushException as e:
    print("ERRORE", e, getattr(e.response, "text", ""), file=sys.stderr)
    sys.exit(1)
`,
);
let status;
try {
  status = execFileSync(
    PYTHON,
    [join(work, 'send.py'), join(work, 'sub.json'), join(work, 'vapid.json')],
    { encoding: 'utf8' },
  ).trim();
} catch (e) {
  await ctx.close();
  fail(`invio rifiutato dal servizio push: ${e.stderr || e.message}`);
}
console.log(`3/4  payload cifrato accettato dal servizio push (HTTP ${status})`);

// 4. Did our worker actually receive and show it?
let shown = [];
for (let i = 0; i < 30; i++) {
  shown = await page.evaluate(async () => {
    const reg = await navigator.serviceWorker.ready;
    return (await reg.getNotifications()).map((n) => ({
      title: n.title,
      body: n.body,
      url: n.data?.url,
    }));
  });
  if (shown.length) break;
  await new Promise((r) => setTimeout(r, 1000));
}
await ctx.close();
rmSync(work, { recursive: true, force: true });

if (!shown.length) fail('nessuna notifica ricevuta entro 30s: la push non è arrivata al worker.');
const n = shown[0];
if (n.title !== 'Ti hanno chiesto un parere' || n.url !== '/decisioni')
  fail(`notifica arrivata ma sbagliata: ${JSON.stringify(n)}`);
console.log(`4/4  notifica mostrata dal service worker: "${n.title}" → ${n.url}`);
console.log('\n✓ Anello completo verificato: VAPID, cifratura, servizio push, service worker.');
