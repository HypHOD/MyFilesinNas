<template>
	<div v-if="visible">
		<!-- 浮动按钮：与 BackTop 同列（right 40），叠在其上方 -->
		<div
			class="fixed right-10 bottom-28 z-10 cursor-pointer select-none"
			@click="openDrawer"
		>
			<el-badge :is-dot="running" :offset="[-2, 4]">
				<div
					class="w-11 h-11 rounded-full bg-white shadow-md flex items-center justify-center hover:shadow-lg transition-shadow"
				>
					<i-mdi-robot-outline class="w-6 h-6 text-blue-500" />
				</div>
			</el-badge>
		</div>

		<el-drawer
			class="agent-drawer"
			:model-value="drawerVisible"
			direction="rtl"
			:size="isMobile ? '100%' : '420px'"
			:with-header="false"
			:modal="false"
			:lock-scroll="false"
			@close="onDrawerClosed"
		>
			<div class="flex flex-col h-full">
				<!-- 头部 -->
				<div
					class="flex items-center px-4 h-12 shrink-0 border-b border-gray-200"
				>
					<span class="font-medium text-gray-700">AI 助手</span>
					<span
						class="w-2 h-2 rounded-full ml-2"
						:class="phaseDotClass"
						:title="phaseLabel"
					></span>
					<div class="ml-auto flex items-center gap-3">
						<el-tooltip content="新对话" placement="bottom">
							<i-mdi-plus
								class="w-5 h-5 cursor-pointer text-gray-500 hover:text-blue-500"
								@click="newSession"
							/>
						</el-tooltip>
						<i-mdi-close
							class="w-5 h-5 cursor-pointer text-gray-500 hover:text-blue-500"
							@click="closeDrawer"
						/>
					</div>
				</div>

				<!-- 状态提示 -->
				<div v-if="banner" class="px-3 pt-2 shrink-0">
					<el-alert
						:title="banner.text"
						:type="banner.type"
						:closable="false"
						show-icon
					/>
					<el-button
						v-if="phase === 'failed'"
						size="small"
						class="mt-2"
						@click="retry"
						>重试</el-button
					>
				</div>

				<!-- 消息区 -->
				<el-scrollbar ref="scrollbarRef" class="flex-1 min-h-0">
					<div class="px-4 py-3">
						<div
							v-if="!messages.length"
							class="text-gray-400 text-sm text-center mt-12 leading-6"
						>
							可以让我查询存储源、列出目录内容、<br />新建文件夹、重命名文件。<br />试试问：列出所有存储源
						</div>

						<template v-for="message in messages" :key="message._id">
							<!-- 提示条 -->
							<div
								v-if="message.kind === 'notice'"
								class="text-center text-xs text-gray-400 my-2"
							>
								{{ message.text }}
							</div>

							<!-- 用户气泡 -->
							<div
								v-else-if="message.role === 'user'"
								class="flex justify-end my-2"
							>
								<div class="max-w-[85%]">
									<div
										class="bg-blue-500 text-white rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap break-words"
										:class="{ 'opacity-60': message.pending }"
									>
										{{ message.text }}
									</div>
									<div
										v-if="message.failed"
										class="text-right text-xs text-red-500 mt-0.5"
									>
										发送失败
									</div>
								</div>
							</div>

							<!-- 助手气泡 -->
							<div v-else-if="message.kind === 'text'" class="flex my-2">
								<div
									class="max-w-[85%] bg-gray-100 text-gray-800 rounded-2xl px-3 py-2 text-sm whitespace-pre-wrap break-words"
								>
									{{ message.text }}
									<span v-if="message.interrupted" class="text-gray-400"
										>（已中断）</span
									>
								</div>
							</div>

							<!-- 工具调用卡 -->
							<details v-else-if="message.kind === 'tool_call'" class="my-1">
								<summary
									class="tool-summary text-xs text-gray-500 inline-flex items-center gap-1 cursor-pointer select-none hover:text-gray-700"
								>
									<i-mdi-loading
										v-if="message.status === 'running'"
										class="w-3.5 h-3.5 animate-spin"
									/>
									<i-mdi-alert-circle-outline
										v-else-if="message.isError"
										class="w-3.5 h-3.5 text-red-500"
									/>
									<i-mdi-check-circle-outline
										v-else
										class="w-3.5 h-3.5 text-green-500"
									/>
									<span>{{ toolLabel(message.name) }}</span>
								</summary>
								<div
									class="mt-1 pl-4 ml-1 border-l border-gray-200 text-xs text-gray-500 font-mono whitespace-pre-wrap break-all max-h-48 overflow-auto"
								>
									<div v-if="message.args && message.args !== '{}'">
										参数: {{ message.args }}
									</div>
									<div
										v-if="message.result"
										class="mt-1"
										:class="{ 'text-red-500': message.isError }"
									>
										结果: {{ message.result }}
									</div>
								</div>
							</details>
						</template>

						<div
							v-if="running"
							class="flex items-center gap-1 text-gray-400 text-sm mt-3"
						>
							<i-mdi-loading class="w-4 h-4 animate-spin" />
							思考中…
						</div>
					</div>
				</el-scrollbar>

				<!-- 输入区 -->
				<div v-if="enabled" class="shrink-0 border-t border-gray-200 p-3">
					<div class="flex items-end gap-2">
						<el-input
							v-model="input"
							type="textarea"
							:autosize="{ minRows: 1, maxRows: 4 }"
							resize="none"
							placeholder="输入问题，Enter 发送，Shift+Enter 换行"
							@keydown.enter.exact="onEnter"
						/>
						<el-button type="primary" :disabled="!canSend" @click="onSend"
							>发送</el-button
						>
						<el-button v-if="running" @click="stopTurn">停止</el-button>
					</div>
				</div>
			</div>
		</el-drawer>
	</div>
</template>

<script setup>
import { isMobile } from '~/utils'
import useStorageConfigStore from '~/stores/storage-config'
import useAgentChat from '~/composables/agent/useAgentChat'

const route = useRoute()
const storageConfigStore = useStorageConfigStore()

const isSharePage = computed(() => !!route.params.shareKey)
const isWatchPage = computed(() => route.path.startsWith('/bangumi'))
const visible = computed(
	() =>
		storageConfigStore.loginInfo.isLogin &&
		!isSharePage.value &&
		!isWatchPage.value
)

const {
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
} = useAgentChat()

const input = ref('')
const scrollbarRef = ref(null)

const canSend = computed(
	() =>
		!!input.value.trim() &&
		!!sessionId.value &&
		enabled.value &&
		phase.value !== 'failed'
)

const phaseDotClass = computed(() => ({
	'bg-green-500': phase.value === 'streaming',
	'bg-yellow-400':
		phase.value === 'connecting' || phase.value === 'reconnecting',
	'bg-red-500': phase.value === 'failed',
	'bg-gray-300': phase.value === 'idle',
}))

const phaseLabel = computed(
	() =>
		({
			streaming: '已连接',
			connecting: '连接中',
			reconnecting: '重连中',
			failed: '连接失败',
			idle: '未连接',
		}[phase.value])
)

const banner = computed(() => {
	if (!enabled.value)
		return {
			text: 'AI 助手未启用（后端未配置 DEEPSEEK_API_KEY）',
			type: 'info',
		}
	if (phase.value === 'reconnecting')
		return { text: '连接中断，重连中…', type: 'warning' }
	if (phase.value === 'failed') return { text: '连接失败', type: 'error' }
	if (lastError.value)
		return { text: `上次出错：${lastError.value}`, type: 'warning' }
	return null
})

const TOOL_LABELS = {
	list_storage_sources: '查询存储源',
	list_files: '列出目录',
	file_info: '文件信息',
	new_folder: '新建文件夹',
	rename: '重命名',
}
const toolLabel = (name) => TOOL_LABELS[name] || name

const onEnter = (e) => {
	// 中文输入法组词中的 Enter 是选字，不能当发送
	if (e.isComposing || e.keyCode === 229) return
	e.preventDefault()
	onSend()
}

const onSend = () => {
	if (!canSend.value) return
	const text = input.value.trim()
	input.value = ''
	sendMessage(text)
}

const onDrawerClosed = () => {
	// ESC 关闭等路径也走这里（closeDrawer/ESC 都会触发 close 事件）
	if (drawerVisible.value) {
		closeDrawer()
	}
}

watch([() => messages.value.length, running], () => {
	nextTick(() => scrollbarRef.value?.setScrollTop(999999))
})

onBeforeUnmount(dispose)
</script>

<style scoped>
.agent-drawer :deep(.el-drawer__body) {
	padding: 0;
	overflow: hidden;
}

/* 收起 details 默认三角，靠状态图标表达 */
.tool-summary {
	list-style: none;
}

.tool-summary::-webkit-details-marker {
	display: none;
}
</style>
