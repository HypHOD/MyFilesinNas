import axios from 'axios'

export const http = axios.create({
  baseURL: '/api/v1',
  timeout: 10000,
})

/** 从错误响应中提取给用户看的中文消息。 */
export function errMsg(e: unknown): string {
  if (axios.isAxiosError(e)) {
    const data = e.response?.data
    if (typeof data?.msg_zh === 'string') return data.msg_zh
    if (typeof data?.detail?.msg_zh === 'string') return data.detail.msg_zh
    return e.message
  }
  return String(e)
}
