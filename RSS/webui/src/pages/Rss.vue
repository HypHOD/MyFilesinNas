<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  NButton,
  NCard,
  NEmpty,
  NInput,
  NList,
  NListItem,
  NPopconfirm,
  NSpace,
  NSwitch,
  NTag,
  useMessage,
} from 'naive-ui'

import { errMsg } from '../api/http'
import {
  addRss,
  deleteRss,
  disableRss,
  enableRss,
  listRss,
  type RSSItem,
} from '../api/rss'

const message = useMessage()
const items = ref<RSSItem[]>([])

const form = ref({ name: '', url: '', aggregate: false })
const adding = ref(false)

async function refresh() {
  try {
    items.value = await listRss()
  } catch (e) {
    message.error(errMsg(e))
  }
}

async function onAdd() {
  if (!form.value.url) {
    message.warning('请填写 RSS 链接')
    return
  }
  adding.value = true
  try {
    await addRss({
      name: form.value.name || undefined,
      url: form.value.url,
      aggregate: form.value.aggregate,
    })
    message.success('添加成功')
    form.value = { name: '', url: '', aggregate: false }
    await refresh()
  } catch (e) {
    message.error(errMsg(e))
  } finally {
    adding.value = false
  }
}

async function onToggle(item: RSSItem) {
  try {
    if (item.enabled) await disableRss(item.id)
    else await enableRss(item.id)
    await refresh()
  } catch (e) {
    message.error(errMsg(e))
  }
}

async function onDelete(id: number) {
  try {
    await deleteRss(id)
    message.success('已删除')
    await refresh()
  } catch (e) {
    message.error(errMsg(e))
  }
}

onMounted(refresh)
</script>

<template>
  <NCard title="RSS 订阅" style="max-width: 800px">
    <NSpace align="center" style="margin-bottom: 16px">
      <NInput
        v-model:value="form.name"
        placeholder="名称（可选）"
        style="width: 140px"
      />
      <NInput
        v-model:value="form.url"
        placeholder="RSS 链接"
        style="width: 300px"
      />
      <NSpace align="center" :size="6">
        <span>聚合</span>
        <NSwitch v-model:value="form.aggregate" size="small" />
      </NSpace>
      <NButton type="primary" :loading="adding" @click="onAdd">添加</NButton>
      <NButton @click="refresh">刷新</NButton>
    </NSpace>

    <NList hoverable>
      <NListItem v-for="item in items" :key="item.id">
        <div
          style="
            display: flex;
            justify-content: space-between;
            align-items: center;
            width: 100%;
          "
        >
          <div style="min-width: 0">
            <div>{{ item.name || '（未命名）' }}</div>
            <div style="color: #999; font-size: 12px; word-break: break-all">
              {{ item.url }}
            </div>
          </div>
          <NSpace align="center" :size="8" style="flex-shrink: 0">
            <NTag :type="item.enabled ? 'success' : 'default'" size="small">
              {{ item.enabled ? '启用' : '停用' }}
            </NTag>
            <NButton size="small" @click="onToggle(item)">
              {{ item.enabled ? '停用' : '启用' }}
            </NButton>
            <NPopconfirm @positive-click="onDelete(item.id)">
              <template #trigger>
                <NButton size="small" type="error" secondary>删除</NButton>
              </template>
              确认删除该订阅？
            </NPopconfirm>
          </NSpace>
        </div>
      </NListItem>
    </NList>
    <NEmpty
      v-if="!items.length"
      description="暂无订阅"
      style="margin-top: 24px"
    />
  </NCard>
</template>
