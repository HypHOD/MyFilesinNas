<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  NButton,
  NCard,
  NEmpty,
  NList,
  NListItem,
  NPopconfirm,
  NSpace,
  NTag,
  useMessage,
} from 'naive-ui'

import { type Bangumi, deleteBangumi, listBangumi } from '../api/bangumi'
import { errMsg } from '../api/http'

const message = useMessage()
const items = ref<Bangumi[]>([])

async function refresh() {
  try {
    items.value = await listBangumi()
  } catch (e) {
    message.error(errMsg(e))
  }
}

async function onDelete(id: number) {
  try {
    await deleteBangumi(id)
    message.success('已删除')
    await refresh()
  } catch (e) {
    message.error(errMsg(e))
  }
}

onMounted(refresh)
</script>

<template>
  <NCard title="番剧" style="max-width: 800px">
    <NSpace style="margin-bottom: 16px">
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
            <div>{{ item.official_title }}</div>
            <div style="color: #999; font-size: 12px; word-break: break-all">
              {{ item.title_raw }} · S{{ item.season }} · 集数偏移
              {{ item.episode_offset }} · 季偏移 {{ item.season_offset }}
            </div>
          </div>
          <NSpace align="center" :size="8" style="flex-shrink: 0">
            <NTag v-if="item.archived" size="small">已归档</NTag>
            <NPopconfirm @positive-click="onDelete(item.id)">
              <template #trigger>
                <NButton size="small" type="error" secondary>删除</NButton>
              </template>
              确认删除该番剧？
            </NPopconfirm>
          </NSpace>
        </div>
      </NListItem>
    </NList>
    <NEmpty
      v-if="!items.length"
      description="暂无番剧"
      style="margin-top: 24px"
    />
  </NCard>
</template>
