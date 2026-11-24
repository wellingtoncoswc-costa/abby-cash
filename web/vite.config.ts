import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import { VitePWA } from 'vite-plugin-pwa'
import { defineConfig } from 'vitest/config'

// Cookie de refresh tem path=/auth: a API precisa estar na mesma origem (proxy em dev, Nginx em prod).
const API = ['/auth', '/spaces', '/accounts', '/cards', '/invoices', '/bills', '/goals', '/channels', '/privacy', '/health']
const target = process.env.API_URL ?? 'http://localhost:8000'

export default defineConfig({
  plugins: [
    react(),
    tailwindcss(),
    VitePWA({
      registerType: 'autoUpdate',
      includeAssets: ['favicon.svg'],
      manifest: {
        name: 'Abby Cash',
        short_name: 'Abby Cash',
        lang: 'pt-BR',
        description: 'Controle financeiro pessoal e familiar',
        theme_color: '#0f766e',
        background_color: '#ffffff',
        display: 'standalone',
        start_url: '/',
        icons: [
          { src: 'icon-192.png', sizes: '192x192', type: 'image/png' },
          { src: 'icon-512.png', sizes: '512x512', type: 'image/png', purpose: 'any maskable' },
        ],
      },
      // a API nunca é cacheada pelo service worker (dados financeiros e tokens)
      workbox: { navigateFallbackDenylist: API.map((p) => new RegExp(`^${p}`)) },
    }),
  ],
  server: { proxy: Object.fromEntries(API.map((p) => [p, { target, changeOrigin: false }])) },
  test: { environment: 'jsdom', globals: true, setupFiles: ['./src/setup.ts'], exclude: ['e2e/**', 'node_modules/**'] },
})
