import { defineConfig } from 'vite'
import vue from '@vitejs/plugin-vue'

// 开发期通过代理访问后端（7892），生产构建产物由后端静态托管
export default defineConfig({
  plugins: [vue()],
  server: {
    port: 5173,
    proxy: {
      '/api': { target: 'http://127.0.0.1:7892', changeOrigin: true },
      '/health': { target: 'http://127.0.0.1:7892', changeOrigin: true },
    },
  },
})
