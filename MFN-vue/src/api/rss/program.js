import { rssHttp } from '~/http/rss'

export const getStatus = () =>
  rssHttp.get('/program/status').then((r) => r.data)

export const startProgram = () =>
  rssHttp.post('/program/start').then((r) => r.data)

export const stopProgram = () => rssHttp.post('/program/stop').then((r) => r.data)

export const restartProgram = () =>
  rssHttp.post('/program/restart').then((r) => r.data)
