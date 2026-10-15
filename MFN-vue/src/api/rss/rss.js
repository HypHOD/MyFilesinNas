import { rssHttp } from '~/http/rss'

export const listRss = () => rssHttp.get('/rss').then((r) => r.data)

export const addRss = (data) => rssHttp.post('/rss/add', data).then((r) => r.data)

export const enableRss = (id) =>
  rssHttp.patch(`/rss/enable/${id}`).then((r) => r.data)

export const disableRss = (id) =>
  rssHttp.patch(`/rss/disable/${id}`).then((r) => r.data)

export const deleteRss = (id) =>
  rssHttp.delete(`/rss/delete/${id}`).then((r) => r.data)
