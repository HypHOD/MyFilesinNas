import { http } from './http'

export interface RSSItem {
  id: number
  name: string | null
  url: string
  aggregate: boolean
  parser: string
  enabled: boolean
  connection_status: string | null
  last_checked_at: string | null
  last_error: string | null
}

export const listRss = () => http.get<RSSItem[]>('/rss').then((r) => r.data)

export const addRss = (data: {
  name?: string
  url: string
  aggregate?: boolean
}) => http.post('/rss/add', data).then((r) => r.data)

export const enableRss = (id: number) =>
  http.patch(`/rss/enable/${id}`).then((r) => r.data)

export const disableRss = (id: number) =>
  http.patch(`/rss/disable/${id}`).then((r) => r.data)

export const deleteRss = (id: number) =>
  http.delete(`/rss/delete/${id}`).then((r) => r.data)
