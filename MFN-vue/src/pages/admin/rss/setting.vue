<template>
  <rss-page>
  <el-form v-if="cfg"
           :model="cfg"
           :label-width="globalConfigStore.adminForm.labelWidth"
           :label-position="globalConfigStore.adminForm.labelPosition"
           :size="globalConfigStore.adminForm.size"
           class="z-admin-form">
    <admin-form-header title="追番设置" hide-bottom-border />

    <el-divider content-position="left">程序</el-divider>
    <el-form-item label="RSS 刷新间隔（秒）">
      <el-input-number v-model="cfg.program.rss_time" :min="1" style="width: 100%" />
    </el-form-item>
    <el-form-item label="重命名间隔（秒）">
      <el-input-number v-model="cfg.program.rename_time" :min="1" style="width: 100%" />
    </el-form-item>
    <el-form-item label="WebUI 端口">
      <el-input-number v-model="cfg.program.webui_port" :min="1" :max="65535" style="width: 100%" />
    </el-form-item>

    <el-divider content-position="left">下载器</el-divider>
    <el-form-item label="类型">
      <el-input v-model="cfg.downloader.type" />
    </el-form-item>
    <el-form-item label="地址">
      <el-input v-model="cfg.downloader.host" placeholder="http://127.0.0.1:8080" />
    </el-form-item>
    <el-form-item label="用户名">
      <el-input v-model="cfg.downloader.username" />
    </el-form-item>
    <el-form-item label="密码">
      <el-input v-model="cfg.downloader.password" type="password" show-password />
    </el-form-item>
    <el-form-item label="保存路径">
      <el-input v-model="cfg.downloader.path" />
    </el-form-item>
    <el-form-item label="SSL">
      <el-switch v-model="cfg.downloader.ssl" />
    </el-form-item>

    <el-form-item class="admin-from-footer">
      <el-button class="ml-auto" type="primary" :icon="CheckBadgeIcon" :loading="saving" @click="save">
        保存设置
      </el-button>
    </el-form-item>
  </el-form>
  </rss-page>
</template>

<script setup>
import { CheckBadgeIcon } from '@heroicons/vue/24/outline'

import { getConfig, updateConfig } from '~/api/rss/config'
import { errMsg } from '~/http/rss'

import useGlobalConfigStore from '~/stores/global-config'
const globalConfigStore = useGlobalConfigStore()

// 未渲染的 rss_parser / bangumi_manage / log 三节随整体对象回传；
// 密码为掩码 ******** 时由后端在保存时还原
const cfg = ref(null)
const saving = ref(false)

async function load() {
  try {
    cfg.value = await getConfig()
  } catch (e) {
    ElMessage.error(errMsg(e))
  }
}

async function save() {
  if (!cfg.value) return
  saving.value = true
  try {
    cfg.value = await updateConfig(cfg.value)
    ElMessage.success('已保存并热重载')
  } catch (e) {
    ElMessage.error(errMsg(e))
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<route lang="yaml">
meta:
  layout: file
  name: 追番设置
</route>
