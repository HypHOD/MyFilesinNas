import { resolve } from 'path'
import Tov from './presets/tov'
import { defineConfig } from 'vite'

export default defineConfig({
	resolve: {
		alias: {
			'~/': `${resolve(__dirname, 'src')}/`,
		},
	},
	build: {
		target: ['es2015'],
		cssTarget: ['chrome49'],
		reportCompressedSize: false
	},
	define: {
		'process.env': {}
	},
	server:{
		host: '0.0.0.0',
		proxy: {
			// RSS 自动追番后端（独立服务），与生产反代保持同一映射：
			// location /rss-api/ { proxy_pass http://rss:7892/api/; }
			'/rss-api': {
				target: 'http://127.0.0.1:7892',
				changeOrigin: true,
				rewrite: (p) => p.replace(/^\/rss-api/, '/api'),
			},
		},
	},
	plugins: [Tov()],
})
