<template>
  <rss-page>
  <div>
    <admin-form-header hide-bottom-border title="番剧管理" />

    <div class="z-admin-table-tools">
      <el-button :icon="ArrowPathIcon" @click="refresh">刷新</el-button>
    </div>

    <el-table-plus border :size="globalConfigStore.adminTable.size" :data="items">
      <el-table-column-plus min-width="260" label="标题">
        <template #default="scope">
          <div>{{ scope.row.official_title }}</div>
          <div class="text-xs text-gray-400 break-all">
            {{ scope.row.title_raw }} · S{{ scope.row.season }} · 集数偏移 {{ scope.row.episode_offset }} · 季偏移
            {{ scope.row.season_offset }}
          </div>
        </template>
      </el-table-column-plus>
      <el-table-column-plus width="90" align="center" label="状态">
        <template #default="scope">
          <el-tag v-if="scope.row.archived" type="info" size="small">已归档</el-tag>
        </template>
      </el-table-column-plus>
      <el-table-column-plus width="90" align="center" label="操作">
        <template #default="scope">
          <el-popconfirm title="是否确认删除?" confirm-button-text="是" cancel-button-text="否" @confirm="onDelete(scope.row.id)">
            <template #reference>
              <TrashIcon class="z-btn-danger" />
            </template>
          </el-popconfirm>
        </template>
      </el-table-column-plus>
    </el-table-plus>
    <el-empty v-if="isMobile && !items.length" description="暂无番剧" />
  </div>
  </rss-page>
</template>

<script setup>
import { ArrowPathIcon, TrashIcon } from '@heroicons/vue/24/outline'
import { isMobile } from '~/utils'

import { deleteBangumi, listBangumi } from '~/api/rss/bangumi'
import { errMsg } from '~/http/rss'

import useGlobalConfigStore from '~/stores/global-config'
const globalConfigStore = useGlobalConfigStore()

const items = ref([])

async function refresh() {
  try {
    items.value = await listBangumi()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

async function onDelete(id) {
  try {
    await deleteBangumi(id)
    ElMessage.success('已删除')
    await refresh()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

onMounted(refresh)
</script>

<route lang="yaml">
meta:
  layout: file
  name: 番剧管理
</route>
