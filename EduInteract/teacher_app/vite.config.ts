import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import { resolve } from 'path'

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, resolve(__dirname, '..'), '')
  const serverPort = parseInt(env.SERVER_PORT || '8766', 10)

  return {
    plugins: [vue()],
    root: '.',
    publicDir: 'public',
    base: './',
    resolve: {
      alias: {
        '@': resolve(__dirname, 'src/client'),
      },
    },
    build: {
      outDir: 'dist/client',
      emptyOutDir: true,
    },
    server: {
      host: '0.0.0.0',
      port: parseInt(env.VITE_PORT || '5175', 10),
      allowedHosts: true,
      proxy: {
        '/api': `http://localhost:${serverPort}`,
        '/doc': `http://localhost:${serverPort}`,
      },
    },
  }
})
