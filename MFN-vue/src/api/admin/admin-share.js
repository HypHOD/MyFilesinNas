import axios from "~/http/request";

// 管理员分页查询分享列表
export const getAdminShareListReq = (params = {}) => {
  return axios({
    url: "/admin/share/list",
    method: "get",
    data: params
  });
};

/**
 * 清理过期分享
 */
export const deleteAllExpiredSharesReq = () => {
	return axios({
		url: '/admin/share/expired',
		method: 'DELETE'
	})
}