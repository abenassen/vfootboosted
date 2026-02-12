import { defineConfig } from 'vite'
import tailwindcss from '@tailwindcss/vite'
import react from '@vitejs/plugin-react'
import path from 'path'
import { fileURLToPath } from 'url'
import flowbiteReact from "flowbite-react/plugin/vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react(), tailwindcss(), flowbiteReact()],
  resolve: {
    alias: {
      '@': path.resolve(path.dirname(fileURLToPath(import.meta.url)), './src'),
      '@components': path.resolve(path.dirname(fileURLToPath(import.meta.url)), './src/components'),
      '@assets': path.resolve(path.dirname(fileURLToPath(import.meta.url)), './src/assets'),
      '@pages': path.resolve(path.dirname(fileURLToPath(import.meta.url)), './src/pages'),
    },
  }
  })