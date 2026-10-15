import axios from 'axios'

import useGlobalConfigStore from '~/stores/global-config'

// 公开看番页（/bangumi）的 axios 实例。
// 不能复用 ~/http/request —— 它的请求拦截器会带上 zfile-token，响应拦截器遇到
// 42000 会跳登录页。看番页要求"无论谁打开都是游客视角"：不携带任何凭证、
// 永不跳转登录，只读访问番剧库白名单（行为完全由后端的 guest 授权行决定）。
export const watchHttp = axios.create({
  timeout: 10000
})

// baseURL 每次请求动态取 zfile.config.json 里的 baseUrl（该配置是异步加载的，
// 模块求值时可能还是空串；生产构建后前端与后端同源，回退 location.origin 也正确）。
watchHttp.interceptors.request.use((config) => {
  const base = useGlobalConfigStore().zfileConfig.baseUrl || window.location.origin
  config.baseURL = base + '/api'
  return config
})

/** 从错误响应中提取给用户看的中文消息。 */
export function errMsg(e) {
  if (axios.isAxiosError(e)) {
    const data = e.response?.data
    if (typeof data?.msg === 'string' && data.msg) return data.msg
    return e.message
  }
  return String(e)
}
