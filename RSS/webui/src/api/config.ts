import { http } from './http'

export interface AppConfig {
  program: {
    rss_time: number
    rename_time: number
    webui_port: number
  }
  downloader: {
    type: string
    host: string
    username: string
    password: string
    path: string
    ssl: boolean
  }
  rss_parser: {
    enable: boolean
    filter: string[]
    language: string
  }
  bangumi_manage: {
    enable: boolean
    eps_complete: boolean
    rename_method: string
    group_tag: boolean
  }
  log: {
    debug_enable: boolean
  }
}

export const getConfig = () =>
  http.get<AppConfig>('/config').then((r) => r.data)

export const updateConfig = (cfg: AppConfig) =>
  http.patch<AppConfig>('/config', cfg).then((r) => r.data)
