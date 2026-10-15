import { http } from './http'

export interface Bangumi {
  id: number
  official_title: string
  title_raw: string
  season: number
  season_raw: string | null
  group_name: string | null
  dpi: string | null
  episode_offset: number
  season_offset: number
  filter: string
  rss_link: string
  poster_link: string | null
  added: boolean
  archived: boolean
  air_weekday: number | null
  episode_type: string
}

export const listBangumi = () =>
  http.get<Bangumi[]>('/bangumi').then((r) => r.data)

export const deleteBangumi = (id: number) =>
  http.delete(`/bangumi/delete/${id}`).then((r) => r.data)

export const updateBangumi = (id: number, data: Partial<Bangumi>) =>
  http.patch(`/bangumi/update/${id}`, data).then((r) => r.data)
