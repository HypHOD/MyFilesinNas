<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  NButton,
  NCard,
  NDivider,
  NForm,
  NFormItem,
  NInput,
  NInputNumber,
  NSwitch,
  useMessage,
} from 'naive-ui'

import { type AppConfig, getConfig, updateConfig } from '../api/config'
import { errMsg } from '../api/http'

const message = useMessage()
const cfg = ref<AppConfig | null>(null)
const saving = ref(false)

async function load() {
  try {
    cfg.value = await getConfig()
  } catch (e) {
    message.error(errMsg(e))
  }
}

async function save() {
  if (!cfg.value) return
  saving.value = true
  try {
    cfg.value = await updateConfig(cfg.value)
    message.success('已保存并热重载')
  } catch (e) {
    message.error(errMsg(e))
  } finally {
    saving.value = false
  }
}

onMounted(load)
</script>

<template>
  <NCard title="设置" style="max-width: 640px">
    <NForm v-if="cfg" label-placement="left" label-width="150">
      <NDivider title-placement="left">程序</NDivider>
      <NFormItem label="RSS 刷新间隔（秒）">
        <NInputNumber
          v-model:value="cfg.program.rss_time"
          :min="1"
          style="width: 100%"
        />
      </NFormItem>
      <NFormItem label="重命名间隔（秒）">
        <NInputNumber
          v-model:value="cfg.program.rename_time"
          :min="1"
          style="width: 100%"
        />
      </NFormItem>
      <NFormItem label="WebUI 端口">
        <NInputNumber
          v-model:value="cfg.program.webui_port"
          :min="1"
          :max="65535"
          style="width: 100%"
        />
      </NFormItem>

      <NDivider title-placement="left">下载器</NDivider>
      <NFormItem label="类型">
        <NInput v-model:value="cfg.downloader.type" />
      </NFormItem>
      <NFormItem label="地址">
        <NInput
          v-model:value="cfg.downloader.host"
          placeholder="http://127.0.0.1:8080"
        />
      </NFormItem>
      <NFormItem label="用户名">
        <NInput v-model:value="cfg.downloader.username" />
      </NFormItem>
      <NFormItem label="密码">
        <NInput
          v-model:value="cfg.downloader.password"
          type="password"
          show-password-on="click"
        />
      </NFormItem>
      <NFormItem label="保存路径">
        <NInput v-model:value="cfg.downloader.path" />
      </NFormItem>
      <NFormItem label="SSL">
        <NSwitch v-model:value="cfg.downloader.ssl" />
      </NFormItem>

      <NFormItem :show-label="false">
        <NButton type="primary" :loading="saving" @click="save">保存</NButton>
      </NFormItem>
    </NForm>
  </NCard>
</template>
