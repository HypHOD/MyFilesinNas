<script setup lang="ts">
import { onMounted, onUnmounted } from 'vue'
import {
  NButton,
  NCard,
  NDescriptions,
  NDescriptionsItem,
  NSpace,
  NTag,
  useMessage,
} from 'naive-ui'

import { errMsg } from '../api/http'
import { useProgramStore } from '../store/program'

const store = useProgramStore()
const message = useMessage()
let timer: number | undefined

async function refreshQuietly() {
  try {
    await store.refresh()
  } catch {
    // 轮询失败静默（后端未启动时页面照常可用）
  }
}

onMounted(() => {
  refreshQuietly()
  timer = window.setInterval(refreshQuietly, 5000)
})
onUnmounted(() => window.clearInterval(timer))

async function action(name: 'start' | 'stop' | 'restart') {
  try {
    if (name === 'start') await store.start()
    else if (name === 'stop') await store.stop()
    else await store.restart()
    message.success('操作成功')
  } catch (e) {
    message.error(errMsg(e))
  }
}
</script>

<template>
  <NCard title="总览" style="max-width: 640px">
    <NDescriptions :column="1" bordered>
      <NDescriptionsItem label="运行状态">
        <NTag :type="store.status?.status ? 'success' : 'default'" size="small">
          {{ store.status?.status ? '运行中' : '已停止' }}
        </NTag>
      </NDescriptionsItem>
      <NDescriptionsItem label="版本">
        {{ store.status?.version ?? '-' }}
      </NDescriptionsItem>
      <NDescriptionsItem label="首次运行">
        {{ store.status?.first_run ? '是' : '否' }}
      </NDescriptionsItem>
    </NDescriptions>
    <NSpace style="margin-top: 16px">
      <NButton
        type="primary"
        :disabled="store.status?.status"
        @click="action('start')"
      >
        启动
      </NButton>
      <NButton :disabled="!store.status?.status" @click="action('stop')">
        停止
      </NButton>
      <NButton @click="action('restart')">重启</NButton>
    </NSpace>
  </NCard>
</template>
