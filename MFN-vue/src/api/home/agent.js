import axios from '~/http/request'

// 新建会话
export const createAgentSessionReq = () => {
	return axios({
		url: '/api/agent/session',
		method: 'post',
		// 50000（未配置 key）由 composable 转成空态文案，不用全局 toast
		config: { showDefaultMsg: false },
	})
}

// 会话状态（40400 = 会话已失效，调用方自行恢复）
export const getAgentSessionReq = (id) => {
	return axios({
		url: `/api/agent/${id}`,
		method: 'get',
		config: { showDefaultMsg: false },
	})
}

// 自己的会话列表
export const listAgentSessionsReq = () => {
	return axios({
		url: '/api/agent/sessions',
		method: 'get',
	})
}

// 发送消息（异步，回答走 SSE）
export const sendAgentMessageReq = (id, content) => {
	return axios({
		url: `/api/agent/${id}/message`,
		method: 'post',
		data: { content },
	})
}

// 中止当前轮次
export const cancelAgentTurnReq = (id) => {
	return axios({
		url: `/api/agent/${id}/cancel`,
		method: 'post',
	})
}

// 关闭会话
export const deleteAgentSessionReq = (id) => {
	return axios({
		url: `/api/agent/${id}`,
		method: 'delete',
	})
}
