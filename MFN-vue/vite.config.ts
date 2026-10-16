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
			// 主后端（DemoFile / FastAPI）。dev 下 baseUrl 为空串（同源），这些前缀经 vite 代理转发，
			// 局域网设备访问 vite 地址时才不会把请求打到设备自己的 127.0.0.1。
			// changeOrigin 保持 false：Host 头原样传给后端，_get_base_url() 据此拼 /pd 播放链接，
			// 指回 vite 地址后再由代理兜回后端（这是看番页无 axios-from 头时链接仍正确的关键）。
			'/api': {
				target: 'http://127.0.0.1:8080',
				changeOrigin: false,
			},
			'/user': {
				target: 'http://127.0.0.1:8080',
				changeOrigin: false,
			},
			'/pd': {
				target: 'http://127.0.0.1:8080',
				changeOrigin: false,
			},
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
