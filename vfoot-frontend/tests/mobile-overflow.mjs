/**
 * Nessuna pagina deve essere più larga del telefono.
 *
 *   VFOOT_E2E_TOKEN=<token> npm run test:mobile
 *
 * Un difetto di questa famiglia non si vede guardando lo schermo: la pagina si
 * allarga di sei pixel, il dito scorre di lato e quello che si rompe è la barra
 * fissa in basso, che resta ancorata alla finestra mentre il contenuto scivola.
 * Si vede MISURANDO — `scrollWidth` contro `clientWidth` — ed è per questo che
 * questo controllo esiste come script invece che come occhiata.
 *
 * E si vede solo con NOMI LUNGHI. Nel database di sviluppo le squadre si
 * chiamano «Team 1», in una lega vera «Anomalia statistica F.C.»: il difetto
 * segnalato il 20/08/2026 (la card «Da fare» che sfondava lo schermo) sul
 * database locale non si sarebbe manifestato mai. Quindi qui i nomi vengono
 * allungati al volo in ogni risposta dell'API, senza toccare il database.
 *
 * Un elemento che sfora NON è di per sé un errore: una tabella o una fila di
 * pillole possono scorrere dentro il loro riquadro, ed è la cosa giusta. Conta
 * solo se a scorrere è la PAGINA. Chi sfora viene stampato lo stesso, perché
 * quando la pagina scorre serve sapere chi la spinge.
 *
 * Cosa serve: `npm run dev`, il backend vero acceso, e il token di un utente che
 * sia dentro la lega indicata (VFOOT_E2E_LEAGUE). Il token si tira fuori così:
 *
 *   vfoot-backend/.venv/bin/python vfoot-backend/src/manage.py shell -c \
 *     "from vfoot.services.auth_tokens import issue_token; \
 *      from django.contrib.auth.models import User; \
 *      print(issue_token(User.objects.get(username='andrea')).key)"
 */
import { chromium } from '@playwright/test';

const ORIGIN = process.env.VFOOT_E2E_BASE_URL || 'http://127.0.0.1:5173';
const TOKEN = process.env.VFOOT_E2E_TOKEN || '';
const LEAGUE = process.env.VFOOT_E2E_LEAGUE || '43';
/** 390 = iPhone 12/13/14 e la maggior parte degli Android in uso: la larghezza
 *  più stretta che valga la pena difendere. Chi sta bene qui sta bene sopra. */
const WIDTH = Number(process.env.VFOOT_E2E_WIDTH || 390);

const PAGINE = (process.env.VFOOT_E2E_PATHS ||
  '/home,/matches,/standings,/squad,/listone,/market,/decisioni,/serie-a,/squad/formation,/league-admin'
).split(',');

/** Nomi lunghi quanto quelli veri, e in tre alfabeti: il cirillico e le lettere
 *  accentate misurano diverso, e una lega di amici li usa. */
const NOMI = {
  1: 'Anomalia statistica F.C. della Bassa',
  2: 'Pagnottelle Kombuccia United',
  3: 'Temptation Haaland Football Club',
  4: 'Vincent Van Goal e i suoi girasoli',
  5: 'Real Sconfitta Internazionale',
  6: 'Legends F.C. dei Tempi Andati',
  7: 'моноболка спортивный клуб',
  8: 'Las pignas de la montaña',
  9: 'Pizzighettone Calcio A.S.D.',
  10: 'Giovane Speranza Riunite',
};

if (!TOKEN) {
  console.error('\n✗ Serve VFOOT_E2E_TOKEN: vedi l\'intestazione di questo file.\n');
  process.exit(2);
}

const browser = await chromium.launch({ channel: 'chrome' });
const context = await browser.newContext({
  viewport: { width: WIDTH, height: 844 },
  deviceScaleFactor: 2,
});

context.route('**/api/v1/**', async (route) => {
  const res = await route.fetch();
  if (!(res.headers()['content-type'] || '').includes('json')) {
    return route.fulfill({ response: res });
  }
  const body = (await res.text()).replace(/Team (\d+)/g, (m, n) => NOMI[Number(n)] || m);
  route.fulfill({ response: res, body });
});

const page = await context.newPage();
await page.goto(`${ORIGIN}/`);
await page.evaluate(
  ([t, l]) => {
    localStorage.setItem('vfoot_auth_token', t);
    localStorage.setItem('vfoot_selected_league_id', l);
  },
  [TOKEN, LEAGUE],
);

let sforanti = 0;
for (const path of PAGINE) {
  await page.goto(`${ORIGIN}${path}`, { waitUntil: 'networkidle' });
  await page.waitForTimeout(1200);
  // UN TOKEN SCADUTO NON DEVE DARE VERDE. L'app rimanda alla pagina pubblica chi
  // non è autenticato, e quella pagina — un modulo di login — sta larga in
  // qualunque schermo: misurandola vien fuori un ✓ per dieci pagine che nessuno
  // ha guardato. È successo il 20/08/2026, ed è il tipo di verde che insegna a
  // fidarsi di un controllo che non controlla niente.
  const dove = new URL(page.url()).pathname;
  if (dove !== path) {
    console.error(
      `\n✗ ${path} ha rimandato a ${dove}: sessione non valida. Conia un token ` +
        `nuovo (vedi l'intestazione) e riprova — quello vecchio muore quando ne ` +
        `viene emesso un altro per lo stesso utente.\n`,
    );
    await browser.close();
    process.exit(2);
  }
  const r = await page.evaluate(() => {
    const de = document.scrollingElement;
    const w = de.clientWidth;
    const colpevoli = [];
    for (const el of document.querySelectorAll('body *')) {
      const b = el.getBoundingClientRect();
      if (b.width === 0 || b.right <= w + 1) continue;
      // Solo il più profondo: se sfora anche il genitore, è il figlio a spingerlo.
      if ([...el.children].some((k) => k.getBoundingClientRect().right > w + 1)) continue;
      colpevoli.push({
        tag: el.tagName.toLowerCase(),
        cls: (el.className?.baseVal ?? el.className ?? '').toString().slice(0, 70),
        right: Math.round(b.right),
        txt: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 44),
      });
    }
    return { larghezza: w, scroll: de.scrollWidth, colpevoli: colpevoli.slice(0, 8) };
  });
  const sfora = r.scroll > r.larghezza;
  if (sfora) sforanti++;
  console.log(
    `${sfora ? '✗' : '✓'} ${path.padEnd(20)} scrollWidth=${r.scroll} / ${r.larghezza}`,
  );
  for (const x of r.colpevoli) {
    console.log(`     ${sfora ? '→' : ' '} ${x.right}px  ${x.tag}  «${x.txt}»  ${x.cls}`);
  }
}

await browser.close();
if (sforanti) {
  console.error(
    `\n✗ ${sforanti} pagin${sforanti === 1 ? 'a' : 'e'} più larg${sforanti === 1 ? 'a' : 'he'} ` +
      `dello schermo. Chi sfora è stampato qui sopra: di solito manca un \`min-w-0\` ` +
      `su un elemento di griglia o di flex, che senza non scende mai sotto la ` +
      `larghezza minima del proprio contenuto.\n`,
  );
  process.exit(1);
}
console.log('\n✓ Nessuna pagina più larga dello schermo.\n');
