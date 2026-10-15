import { watchHttp } from '~/http/watch'

// 公开看番页固定使用 local 存储源（后续需要时可改为取 /api/storage/list 第一项）。
export const WATCH_STORAGE_KEY = 'local'

// zfile 后端响应封套 {code, msg, data}，code 为字符串 '0' 表示成功。
const unwrap = (res) => {
  const body = res.data
  if (body.code !== '0') {
    const err = new Error(body.msg || '请求失败')
    err.bizCode = body.code
    throw err
  }
  return body.data
}

/**
 * 拉取指定目录的文件列表，文件项带短时效签名 url。
 * path 相对游客白名单根（后端 guest 行 root_path=/Bangumi），'' 或 '/' 表示根。
 */
export const fetchWatchFiles = (path) =>
  watchHttp.post('/storage/files', { storageKey: WATCH_STORAGE_KEY, path: path || '/' }).then(unwrap)

/**
 * 拉取存储源配置（含游客权限位），用于灌入 storageConfigStore.folderConfig。
 * 播放器右键菜单、权限按钮等据此判断（游客 download=false → 不出现下载项）。
 */
export const fetchWatchStorageConfig = (path) =>
  watchHttp.post('/site/config/storage', { storageKey: WATCH_STORAGE_KEY, path: path || '/' }).then(unwrap)
