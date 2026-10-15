<template>
  <rss-page>
  <div>
    <admin-form-header hide-bottom-border title="RSS 订阅" />

    <el-form inline
             class="z-admin-search-from"
             :size="globalConfigStore.adminSearch.size"
             label-width="80"
             :label-position="globalConfigStore.adminSearch.labelPosition"
             :model="form">
      <el-row class="z-admin-search-from-row" :gutter="20">
        <el-col :span="globalConfigStore.adminSearch.spanSize">
          <el-form-item label="名称">
            <el-input v-model="form.name" placeholder="名称（可选）" />
          </el-form-item>
        </el-col>
        <el-col :span="globalConfigStore.adminSearch.spanSize">
          <el-form-item label="链接">
            <el-input v-model="form.url" placeholder="RSS 链接" />
          </el-form-item>
        </el-col>
        <el-col :span="globalConfigStore.adminSearch.spanSize">
          <el-form-item label="聚合">
            <el-switch v-model="form.aggregate" />
          </el-form-item>
        </el-col>
        <el-col :span="globalConfigStore.adminSearch.spanSize">
          <el-button type="primary" :icon="PlusIcon" :loading="adding" @click="onAdd">
            添加
          </el-button>
          <el-button :icon="ArrowPathIcon" @click="refresh">刷新</el-button>
        </el-col>
      </el-row>
    </el-form>

    <el-table-plus border :size="globalConfigStore.adminTable.size" :data="items">
      <el-table-column-plus min-width="160" label="名称">
        <template #default="scope">
          {{ scope.row.name || '（未命名）' }}
        </template>
      </el-table-column-plus>
      <el-table-column-plus min-width="240" show-overflow-tooltip prop="url" label="链接" />
      <el-table-column-plus align="center" header-align="center" width="115" prop="enabled" label="启用状态">
        <template #default="scope">
          <el-switch v-model="scope.row.enabled" @change="onToggle(scope.row)" />
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
    <el-empty v-if="isMobile && !items.length" description="暂无订阅" />
  </div>
  </rss-page>
</template>

<script setup>
import { ArrowPathIcon, PlusIcon, TrashIcon } from '@heroicons/vue/24/outline'
import { isMobile } from '~/utils'

import { addRss, deleteRss, disableRss, enableRss, listRss } from '~/api/rss/rss'
import { errMsg } from '~/http/rss'

import useGlobalConfigStore from '~/stores/global-config'
const globalConfigStore = useGlobalConfigStore()

const items = ref([])
const form = reactive({ name: '', url: '', aggregate: false })
const adding = ref(false)

async function refresh() {
  try {
    items.value = await listRss()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

async function onAdd() {
  if (!form.url) {
    ElMessage.warning('请填写 RSS 链接')
    return
  }
  adding.value = true
  try {
    await addRss({
      name: form.name || undefined,
      url: form.url,
      aggregate: form.aggregate
    })
    ElMessage.success('添加成功')
    form.name = ''
    form.url = ''
    form.aggregate = false
    await refresh()
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    adding.value = false
  }
}

async function onToggle(row) {
  try {
    if (row.enabled) await disableRss(row.id)
    else await enableRss(row.id)
    await refresh()
  } catch (e) {
    // el-switch 已先行切换 v-model，请求失败时回滚
    row.enabled = !row.enabled
    ElMessage.error(errMsg(e))
  }
}

async function onDelete(id) {
  try {
    await deleteRss(id)
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
  name: RSS 订阅
</route>
