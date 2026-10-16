import { ElMessage, ElMessageBox } from 'element-plus'
import {
	createAgentSessionReq,
	getAgentSessionReq,
	sendAgentMessageReq,
	cancelAgentTurnReq,
	deleteAgentSessionReq,
} from '~/api/home/agent'
import useGlobalConfigStore from '~/stores/global-config'

/**
 * AI 助手聊天状态（模块级单例，组件卸载后保留，抽屉重开增量续订）。
 *
 * 事件流：EventSource 原生实现，URL 带 ?since=lastSeq&token=...（浏览器无法给
 * EventSource 设自定义头，走后端 ?token= 兜底）。内建重连会复用旧 URL（旧 since），
 * 不可依赖 —— onerror 时必须 close 并重建 URL。
 */

const STORAGE_KEY = 'zfile-agent-session-id'
const MAX_RETRIES = 3

const EVENT_TYPES = [
	'system/message',
	'user/message',
	'assistant/message',
	'tool/call',
	'tool/result',
	'turn/start',
	'turn/end',
	'step/start',
	'step/end',
]

const drawerVisible = ref(false)
const phase = ref('idle') // idle / connecting / streaming / reconnecting / failed
const enabled = ref(true) // 后端未配置 DEEPSEEK_API_KEY 时为 false
const running = ref(false)
const sessionId = ref(null)
const messages = ref([])
const lastSeq = ref(-1)
const lastError = ref(null)

let es = null
let retries = 0
let nextMsgId = 0

const pushMessage = (message) => {
	message._id = nextMsgId++
	messages.value.push(message)
	return message
}

const pushNotice = (text) =>
	pushMessage({ role: 'system', kind: 'notice', text })

const blocksToText = (message) =>
	(message?.content || [])
		.filter((b) => b.type === 'text')
		.map((b) => b.text)
		.join('')

const getToken = () => {
	let token = window.localStorage.getItem('zfile-token')
	if (!token) {
		const cookieToken = document.cookie
			.split('; ')
			.find((row) => row.startsWith('zfile-token='))
		if (cookieToken) {
			token = cookieToken.split('=')[1]
		}
	}
	return token || ''
}

// 信封错误两种形态：HTTP 非 2xx 走 error.response.data，HTTP 200 但 code!=0 直接 reject(response)
const errCode = (e) => e?.response?.data?.code ?? e?.data?.code

const applyStatus = (status) => {
	if (!status) return
	running.value = status.status === 'running'
	lastError.value = status.lastError || null
}

const createSession = async () => {
	try {
		const res = await createAgentSessionReq()
		sessionId.value = res.data.id
		window.localStorage.setItem(STORAGE_KEY, res.data.id)
		// 换会话必须重置游标：seq 从 0 重新计，旧 lastSeq 会把新日志全去重掉
		lastSeq.value = -1
		applyStatus(res.data)
		enabled.value = true
		phase.value = 'idle'
		return true
	} catch (e) {
		if (errCode(e) === '50000') {
			enabled.value = false
			phase.value = 'idle'
		} else {
			phase.value = 'failed'
		}
		return false
	}
}

const ensureSession = async () => {
	if (sessionId.value) {
		return true
	}
	const stored = window.localStorage.getItem(STORAGE_KEY)
	if (stored) {
		try {
			const res = await getAgentSessionReq(stored)
			sessionId.value = stored
			applyStatus(res.data)
			return true
		} catch (e) {
			// 40400（后端重启/会话被删）→ 落到新建；其他错误也交给新建兜底
		}
	}
	return await createSession()
}

const upsertToolCall = (block) => {
	let card = messages.value.find(
		(m) => m.kind === 'tool_call' && m.callId === block.id
	)
	if (!card) {
		card = pushMessage({
			role: 'tool',
			kind: 'tool_call',
			callId: block.id,
			name: block.name,
			args: block.arguments,
			status: 'running',
		})
	} else {
		card.name = block.name ?? card.name
		if (block.arguments) card.args = block.arguments
	}
}

const handleEvent = (type, e) => {
	const seq = Number(e.lastEventId)
	if (!Number.isFinite(seq) || seq <= lastSeq.value) return
	lastSeq.value = seq

	let data
	try {
		data = JSON.parse(e.data)
	} catch (parseError) {
		return
	}

	switch (type) {
		case 'user/message': {
			const text = blocksToText(data.message)
			const pending = messages.value.find(
				(m) => m.role === 'user' && m.pending && m.text === text
			)
			if (pending) {
				pending.pending = false
			} else {
				pushMessage({ role: 'user', kind: 'text', text })
			}
			break
		}
		case 'assistant/message': {
			for (const block of data.message?.content || []) {
				if (block.type === 'text' && block.text) {
					pushMessage({
						role: 'assistant',
						kind: 'text',
						text: block.text,
						interrupted: !!data.interrupted,
					})
				} else if (block.type === 'tool_call') {
					upsertToolCall(block)
				}
			}
			break
		}
		case 'tool/call':
			upsertToolCall({
				id: data.callId,
				name: data.name,
				arguments: data.arguments,
			})
			break
		case 'tool/result': {
			const card = messages.value.find(
				(m) => m.kind === 'tool_call' && m.callId === data.callId
			)
			if (card) {
				card.result = data.content
				card.isError = !!data.isError
				card.status = 'done'
			}
			break
		}
		case 'turn/start':
			running.value = true
			lastError.value = null
			break
		case 'turn/end':
			running.value = false
			if (data.status === 'error') {
				pushNotice('本轮出错，可重试')
			} else if (data.status === 'canceled') {
				pushNotice('已终止')
			}
			break
		// system/message 是系统提示词，不渲染；step/* 不在 UI 呈现粒度内
	}
}

const teardownStream = () => {
	if (es) {
		es.close()
		es = null
	}
}

const diagnose = async () => {
	retries = 0
	try {
		const res = await getAgentSessionReq(sessionId.value)
		applyStatus(res.data)
		lastError.value = null
		connect()
	} catch (e) {
		if (errCode(e) === '40400') {
			// 后端重启/他端删除：旧日志保留展示，新会话继续对话
			const ok = await createSession()
			if (ok) {
				pushNotice('会话已失效，已新建会话')
				connect()
			}
		} else {
			phase.value = 'failed'
		}
	}
}

const connect = () => {
	if (!sessionId.value || !enabled.value || !drawerVisible.value) {
		return
	}
	teardownStream()
	phase.value = phase.value === 'reconnecting' ? 'reconnecting' : 'connecting'

	const base = useGlobalConfigStore().zfileConfig.baseUrl || ''
	const url =
		`${base}/api/agent/${sessionId.value}/events` +
		`?since=${lastSeq.value}&token=${encodeURIComponent(getToken())}`

	const source = new EventSource(url)
	es = source
	source.onopen = () => {
		phase.value = 'streaming'
		retries = 0
	}
	source.onerror = () => {
		if (es !== source) return // 已被新连接替换的旧回调
		source.close()
		es = null
		phase.value = 'reconnecting'
		if (retries < MAX_RETRIES) {
			const delay = 1000 * 2 ** retries
			retries += 1
			setTimeout(() => {
				if (drawerVisible.value) connect()
			}, delay)
		} else {
			diagnose()
		}
	}
	for (const type of EVENT_TYPES) {
		source.addEventListener(type, (e) => handleEvent(type, e))
	}
}

const openDrawer = async () => {
	drawerVisible.value = true
	if (sessionId.value) {
		connect()
		return
	}
	phase.value = 'connecting'
	const ok = await ensureSession()
	if (ok) connect()
}

const closeDrawer = () => {
	drawerVisible.value = false
	teardownStream()
	phase.value = 'idle'
}

const sendMessage = async (text) => {
	text = (text || '').trim()
	if (!text || !sessionId.value || !enabled.value) return
	pushMessage({ role: 'user', kind: 'text', text, pending: true })
	try {
		await sendAgentMessageReq(sessionId.value, text)
	} catch (e) {
		const bubble = [...messages.value]
			.reverse()
			.find((m) => m.role === 'user' && m.pending && m.text === text)
		if (bubble) {
			bubble.pending = false
			bubble.failed = true
		}
	}
}

const stopTurn = async () => {
	if (!running.value || !sessionId.value) return
	try {
		await cancelAgentTurnReq(sessionId.value)
	} catch (e) {
		ElMessage.error('中止失败')
	}
}

const newSession = async () => {
	try {
		await ElMessageBox.confirm('确定开始新对话？当前对话将关闭。', '提示', {
			confirmButtonText: '确定',
			cancelButtonText: '取消',
			type: 'warning',
		})
	} catch (e) {
		return // 用户取消
	}
	const old = sessionId.value
	teardownStream()
	sessionId.value = null
	messages.value = []
	lastSeq.value = -1
	lastError.value = null
	running.value = false

	const ok = await createSession()
	if (ok) {
		connect()
	}
	if (old && old !== sessionId.value) {
		try {
			await deleteAgentSessionReq(old)
		} catch (e) {
			// 旧会话清理失败不影响新会话
		}
	}
}

const retry = () => {
	retries = 0
	diagnose()
}

const dispose = () => {
	teardownStream()
	drawerVisible.value = false
	phase.value = 'idle'
}

export default function useAgentChat() {
	return {
		drawerVisible,
		phase,
		enabled,
		running,
		sessionId,
		messages,
		lastError,
		openDrawer,
		closeDrawer,
		sendMessage,
		stopTurn,
		newSession,
		retry,
		dispose,
	}
}
