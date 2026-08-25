import { defineConfig, loadEnv, type Plugin } from 'vite';
import react from '@vitejs/plugin-react';
import { VitePWA } from 'vite-plugin-pwa';

/** PWA notes, because two of these settings are the difference between a working
 *  app and a confusing one.
 *
 *  `injectManifest` rather than `generateSW`: we write the service worker
 *  ourselves (src/sw.ts) because it has to handle `push` and `notificationclick`,
 *  which a generated one knows nothing about. Workbox still injects the precache
 *  list into it.
 *
 *  The precache list is the BUILD OUTPUT only — JS/CSS whose filenames carry a
 *  content hash, so caching them forever is safe by construction. Nothing under
 *  /api/ is cached anywhere, at any time: a service worker serving a stale API
 *  response shows last week's votes with nothing on screen to explain why, and it
 *  is the single easiest way to make a PWA worse than the site it replaced.
 */
/** Refuses to build a deployable bundle configured for a developer's laptop.
 *
 *  `VITE_*` values are substituted at BUILD time, so a bare `npm run build` does
 *  not produce an unconfigured bundle: it silently inherits `.env.local`, bakes
 *  `http://localhost:8000/api/v1` into the shipped JS, and every visitor's browser
 *  then calls its own machine. Nothing errors — not the build, not the console,
 *  not nginx — so the first sign is users unable to log in. That shipped to
 *  production on 25/08/2026; this plugin is why it cannot ship again.
 *
 *  The same substitution deletes the Google button: with no client id the effect
 *  returns on its first line and the minifier drops the whole sign-in path, so a
 *  missing id is not a broken button but no button at all.
 *
 *  Deliberate local production builds (the offline-shell test, a preview against
 *  a dev backend) set VFOOT_LOCAL_BUILD=1. Forgetting anything else fails the
 *  build, which is the only outcome that cannot reach users.
 */
function guardProductionEnv(): Plugin {
  return {
    name: 'vfoot-guard-production-env',
    apply: 'build',
    config(_config, { mode }) {
      if (process.env.VFOOT_LOCAL_BUILD === '1') return;

      const env = loadEnv(mode, process.cwd(), 'VITE_');
      const problems: string[] = [];

      const base = env.VITE_API_BASE_URL?.trim();
      if (!base) {
        problems.push('VITE_API_BASE_URL manca: il bundle ripiegherebbe su http://localhost:8000/api/v1.');
      } else if (/localhost|127\.0\.0\.1|\[::1\]|0\.0\.0\.0/.test(base)) {
        problems.push(`VITE_API_BASE_URL vale ${base} — e' l'indirizzo di sviluppo: in produzione ogni browser chiamerebbe se stesso. Deve essere /api/v1, relativo.`);
      }

      const clientId = env.VITE_GOOGLE_CLIENT_ID?.trim();
      if (!clientId) {
        problems.push('VITE_GOOGLE_CLIENT_ID manca: il bottone "Accedi con Google" verrebbe cancellato dal bundle, senza errori.');
      } else if (!clientId.endsWith('.apps.googleusercontent.com')) {
        problems.push(`VITE_GOOGLE_CLIENT_ID vale ${clientId}, che non e' un client id Google.`);
      }

      if (problems.length > 0) {
        throw new Error(
          ['', 'Build di produzione rifiutata:', ...problems.map((p) => `  - ${p}`), '',
           'Usa il comando intero di deploy/DEPLOY.md §1:', '',
           '  VITE_API_PROVIDER=backend \\', '  VITE_API_BASE_URL=/api/v1 \\',
           '  VITE_GOOGLE_CLIENT_ID=<client id>.apps.googleusercontent.com \\', '  npm run build', '',
           'Per una build locale volutamente puntata al backend di sviluppo: VFOOT_LOCAL_BUILD=1 npm run build', ''
          ].join('\n')
        );
      }
    },
  };
}

export default defineConfig({
  plugins: [
    guardProductionEnv(),
    react(),
    VitePWA({
      strategies: 'injectManifest',
      srcDir: 'src',
      filename: 'sw.ts',
      registerType: 'prompt',
      injectRegister: null, // we register by hand, to drive the update prompt
      manifest: {
        id: '/',
        name: 'Vfoot Boosted',
        short_name: 'Vfoot',
        description: 'Fantacalcio sui dati reali: voti, aste, mercato e decisioni di lega.',
        lang: 'it',
        start_url: '/home',
        scope: '/',
        display: 'standalone',
        orientation: 'portrait',
        background_color: '#f8fafc',
        theme_color: '#0f172a',
        icons: [
          { src: '/icons/icon-192.png', sizes: '192x192', type: 'image/png', purpose: 'any' },
          { src: '/icons/icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any' },
          // Android crops icons to the launcher's shape: the maskable pair keeps
          // the artwork inside the safe circle so the logo is not clipped.
          { src: '/icons/maskable-192.png', sizes: '192x192', type: 'image/png', purpose: 'maskable' },
          { src: '/icons/maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      injectManifest: {
        // A CLASSIC script, not an ES module: module service workers are still not
        // universally supported (Firefox), and a worker that fails to register
        // takes the offline shell and the notifications down with it.
        rollupFormat: 'iife',
        globPatterns: ['**/*.{js,css,html,ico,png,svg,woff2}'],
        // The logo is 1.3 MB and is imported by the shell, so the default 2 MiB
        // cap would silently drop it from the precache.
        maximumFileSizeToCacheInBytes: 4 * 1024 * 1024,
      },
      devOptions: {
        // A service worker in `npm run dev` is what makes the whole thing
        // testable without a production build.
        enabled: true,
        type: 'module',
        // No `navigateFallback` here on purpose. It installs a SECOND navigation
        // route, ahead of the one src/sw.ts registers, and that one knows nothing
        // about the denylist — so in dev (and only in dev) a request for a real
        // file in public/, like /mobile-frame.html, was answered with the SPA shell
        // and ended on the app's own 404. The worker's own route already does the
        // job, with the denylist, in dev and in production alike.
      },
    }),
  ],
  server: {
    port: 5173,
    strictPort: true,
  },
});
