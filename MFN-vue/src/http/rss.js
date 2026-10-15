import axios from 'axios'

// RSS 后端（独立服务）的 axios 实例。
// 不能复用 ~/http/request：其响应封套 {code,msg,data} 与 RSS 后端不兼容，
// 且 request 包装不支持 PATCH（RSS 的 enable/disable/updateConfig 全是 PATCH）。
// RSS 后端无 CORS 头，baseURL 必须用相对路径经 vite 代理转发（见 vite.config.ts）。
export const rssHttp = axios.create({
  baseURL: '/rss-api/v1',
  timeout: 10000
})

/** 从错误响应中提取给用户看的中文消息。 */
export function errMsg(e) {
  if (axios.isAxiosError(e)) {
    const data = e.response?.data
    if (typeof data?.msg_zh === 'string') return data.msg_zh
    if (typeof data?.detail?.msg_zh === 'string') return data.detail.msg_zh
    return e.message
  }
  return String(e)
}
