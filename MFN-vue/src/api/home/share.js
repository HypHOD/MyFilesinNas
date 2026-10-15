import axios from "~/http/request"

import useGlobalConfigStore from "~/stores/global-config";
let globalConfigStore = useGlobalConfigStore();

/**
 * 创建分享链接
 * @param {Object} params - 创建分享参数
 * @param {string} params.storageKey - 存储源key
 * @param {string} params.sharePath - 分享所在目录路径
 * @param {Array<{name: string, type: 'FILE'|'FOLDER'}>} params.shareEntries - 分享条目列表
 * @param {string} params.shareType - 分享类型 (FILE/FOLDER/MULTIPLE)
 * @param {string} [params.password] - 分享密码（可选）
 * @param {Date} [params.expireDate] - 过期时间（可选）
 * @param {string} [params.shareKey] - 自定义分享key（可选）
 */
export const createShareLinkReq = (params) => {
  return axios({
    url: '/api/share/create',
    method: 'POST',
    data: params
  })
}

/**
 * 获取分享信息（无需密码）
 * @param {string} shareKey - 分享链接key
 */
export const getShareInfoReq = (shareKey) => {
  // 关闭默认错误弹窗，由页面自行处理无效分享文案
  return axios({
    url: `/api/share/info/${shareKey}`,
    method: 'GET',
    config: { showDefaultMsg: false }
  })
}

/**
 * 验证分享密码
 * @param {Object} params - 验证参数
 * @param {string} params.shareKey - 分享链接key
 * @param {string} params.password - 分享密码
 */
export const verifySharePasswordReq = (params) => {
  return axios({
    url: '/api/share/verify',
    method: 'POST',
    data: params
  })
}

/**
 * 获取分享文件列表
 * @param {Object} params - 请求参数
 * @param {string} params.shareKey - 分享链接key
 * @param {string} [params.path] - 文件路径（可选，默认为根路径）
 * @param {string} [params.password] - 分享密码（可选）
 * @param {string} [params.orderBy] - 排序字段（可选，默认为name）
 * @param {string} [params.orderDirection] - 排序方向（可选，默认为asc）
 */
export const getShareFileListReq = (params) => {
  return axios({
    url: '/api/share/files',
    method: 'POST',
    data: params,
    showDefaultMsg: false
  })
}

/**
 * 获取分享文件下载链接
 * @param {string} shareKey - 分享链接key
 * @param {string} path - 文件路径
 * @param {string} [password] - 分享密码（可选）
 */
export const getShareFileDownloadUrlReq = (shareKey, path, password) => {
  const params = new URLSearchParams({
    path,
    ...(password && { password })
  })
  
  return globalConfigStore.serverAddress + `/api/share/download/${shareKey}?${params.toString()}`
}

/**
 * 获取用户分享列表
 */
export const getUserShareListReq = (params = {}) => {
  return axios({
    url: '/api/share/list',
    method: 'GET',
    data: params
  })
}

/**
 * 删除分享链接
 * @param {string} shareKey - 分享链接key
 */
export const deleteShareReq = (shareKey) => {
  return axios({
    url: `/api/share/${shareKey}`,
    method: 'DELETE'
  })
}

/**
 * 清理过期分享
 */
export const deleteExpiredSharesReq = () => {
  return axios({
    url: '/api/share/expired',
    method: 'DELETE'
  })
}
