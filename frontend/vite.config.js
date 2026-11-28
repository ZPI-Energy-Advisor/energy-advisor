import { defineConfig } from 'vite'
import react, { reactCompilerPreset } from '@vitejs/plugin-react'
import babel from '@rolldown/plugin-babel'
import { VitePWA } from 'vite-plugin-pwa'

// https://vite.dev/config/
export default defineConfig({
  envDir: '..',
  plugins: [
    react(),
    babel({ presets: [reactCompilerPreset()] }),
    // Aplikacja do zainstalowania na telefonie (PWA): manifest, ikony i service worker, który trzyma w pamięci
    // tylko pliki aplikacji. Dane z API (ceny, stan domu, plany) zawsze idą z sieci, żeby nie pokazać starych.
    // Nową wersję włącza użytkownik paskiem „Jest nowa wersja” (registerType: prompt), a nie w trakcie pracy.
    VitePWA({
      registerType: 'prompt',
      injectRegister: false,
      includeAssets: ['favicon.svg', 'icons/apple-touch-icon.png'],
      manifest: {
        name: 'Energy Advisor',
        short_name: 'Energy Advisor',
        description: 'Rachunki za prąd, taryfy, ceny dynamiczne i plan zużycia na jutro.',
        lang: 'pl',
        start_url: '/dashboard',
        scope: '/',
        display: 'standalone',
        background_color: '#ffffff',
        theme_color: '#059669',
        icons: [
          { src: '/icons/pwa-192.png', sizes: '192x192', type: 'image/png' },
          { src: '/icons/pwa-512.png', sizes: '512x512', type: 'image/png' },
          { src: '/icons/pwa-maskable-512.png', sizes: '512x512', type: 'image/png', purpose: 'maskable' },
        ],
      },
      workbox: {
        globPatterns: ['**/*.{js,css,html,svg,png,woff2}'],
        globIgnores: ['samples/**'],
        navigateFallback: '/index.html',
        cleanupOutdatedCaches: true,
      },
    }),
  ],
  // `npm run dev` i `vite preview`: /api do backendu na porcie 8000, tak jak nginx w kontenerze frontendu.
  // `host: true` pozwala otworzyć aplikację z telefonu w tej samej sieci (http://IP-komputera:5173).
  server: {
    host: true,
    proxy: { '/api': 'http://localhost:8000' },
  },
  preview: {
    host: true,
    proxy: { '/api': 'http://localhost:8000' },
  },
  test: {
    environment: 'jsdom',
    setupFiles: ['./src/test/setup.js'],
  },
})
