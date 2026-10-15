<script setup lang="ts">
import { computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import {
  NConfigProvider,
  NLayout,
  NLayoutContent,
  NLayoutSider,
  NMenu,
  NMessageProvider,
} from 'naive-ui'

const route = useRoute()
const router = useRouter()

const menuOptions = [
  { label: '总览', key: '/' },
  { label: 'RSS 订阅', key: '/rss' },
  { label: '番剧', key: '/bangumi' },
  { label: '设置', key: '/settings' },
]
const activeKey = computed(() => route.path)
</script>

<template>
  <NConfigProvider>
    <NMessageProvider>
      <NLayout has-sider style="height: 100vh">
        <NLayoutSider bordered :width="200">
          <div style="padding: 16px; font-weight: 600">Auto_Bangumi 复现</div>
          <NMenu
            :options="menuOptions"
            :value="activeKey"
            @update:value="(key: string) => router.push(key)"
          />
        </NLayoutSider>
        <NLayoutContent :native-scrollbar="false" style="padding: 24px">
          <RouterView />
        </NLayoutContent>
      </NLayout>
    </NMessageProvider>
  </NConfigProvider>
</template>
