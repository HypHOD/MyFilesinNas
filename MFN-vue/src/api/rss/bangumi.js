import { rssHttp } from '~/http/rss'

export const listBangumi = () => rssHttp.get('/bangumi').then((r) => r.data)

export const deleteBangumi = (id) =>
  rssHttp.delete(`/bangumi/delete/${id}`).then((r) => r.data)

export const updateBangumi = (id, data) =>
  rssHttp.patch(`/bangumi/update/${id}`, data).then((r) => r.data)
