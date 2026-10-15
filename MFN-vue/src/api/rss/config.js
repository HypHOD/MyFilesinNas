import { rssHttp } from '~/http/rss'

export const getConfig = () => rssHttp.get('/config').then((r) => r.data)

export const updateConfig = (cfg) => rssHttp.patch('/config', cfg).then((r) => r.data)
