import { defineConfig } from 'vite';
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
export default defineConfig({
  plugins: [
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
        navigateFallback: 'index.html',
      },
    }),
  ],
  server: {
    port: 5173,
    strictPort: true,
  },
});
