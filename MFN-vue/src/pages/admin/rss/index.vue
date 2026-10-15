<template>
  <rss-page>
  <div>
    <admin-form-header hide-bottom-border title="追番总览" />

    <el-descriptions :column="1" border style="max-width: 640px">
      <el-descriptions-item label="运行状态">
        <el-tag :type="store.status?.status ? 'success' : 'info'" size="small">
          {{ store.status?.status ? '运行中' : '已停止' }}
        </el-tag>
      </el-descriptions-item>
      <el-descriptions-item label="版本">
        {{ store.status?.version ?? '-' }}
      </el-descriptions-item>
      <el-descriptions-item label="首次运行">
        {{ store.status?.first_run ? '是' : '否' }}
      </el-descriptions-item>
    </el-descriptions>

    <div class="mt-4">
      <el-button type="primary" :disabled="store.status?.status" @click="action('start')">
        启动
      </el-button>
      <el-button type="danger" :disabled="!store.status?.status" @click="action('stop')">
        停止
      </el-button>
      <el-button @click="action('restart')">重启</el-button>
    </div>
  </div>
  </rss-page>
</template>

<script setup>
import { errMsg } from '~/http/rss'
import { useRssProgramStore } from '~/stores/rss-program'

const store = useRssProgramStore()
let timer

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

async function action(name) {
  try {
    if (name === 'start') await store.start()
    else if (name === 'stop') await store.stop()
    else await store.restart()
    ElMessage.success('操作成功')
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}
</script>

<route lang="yaml">
meta:
  layout: file
  name: 追番总览
</route>
