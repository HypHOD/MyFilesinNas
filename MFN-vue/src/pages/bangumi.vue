<template>
  <div class="zfile-index-body">
    <div class="zfile-index-table-card">
      <div class="z-file-view bangumi-page">

        <!-- 顶部栏：面包屑 + 刷新 -->
        <div class="bangumi-toolbar">
          <el-breadcrumb separator="/">
            <el-breadcrumb-item>
              <span
                class="bangumi-crumb"
                :class="{ 'is-current': pathStack.length === 0 }"
                @click="goTo(-1)"
              >番剧库</span>
            </el-breadcrumb-item>
            <el-breadcrumb-item v-for="(seg, i) in pathStack" :key="i">
              <span
                class="bangumi-crumb"
                :class="{ 'is-current': i === pathStack.length - 1 }"
                @click="goTo(i)"
              >{{ seg }}</span>
            </el-breadcrumb-item>
          </el-breadcrumb>
          <el-button size="small" :loading="loading" @click="load()">刷新</el-button>
        </div>

        <!-- 加载态 -->
        <div v-if="loading && items.length === 0" class="bangumi-status">
          <p class="bangumi-status-text">加载中...</p>
        </div>

        <!-- 错误态 -->
        <div v-else-if="error" class="bangumi-status">
          <svg-icon name="404" class="bangumi-status-icon" />
          <p class="bangumi-status-text">{{ error }}</p>
          <el-button type="primary" @click="load()">重试</el-button>
        </div>

        <!-- 空态 -->
        <div v-else-if="folders.length === 0 && episodes.length === 0" class="bangumi-status">
          <svg-icon name="empty" class="bangumi-status-icon" />
          <p class="bangumi-status-text">暂无内容</p>
        </div>

        <template v-else>
          <!-- 子目录（番剧/季）卡片 -->
          <div v-if="folders.length" class="bangumi-grid">
            <div
              v-for="folder in folders"
              :key="folder.name"
              class="bangumi-card"
              @click="enterFolder(folder)"
            >
              <svg-icon name="file-type-folder" class="bangumi-card-icon" color="#5b9bd5" />
              <div class="bangumi-card-name" :title="folder.name">{{ folder.name }}</div>
            </div>
          </div>

          <!-- 剧集列表（视频文件） -->
          <div v-if="episodes.length" class="bangumi-episodes">
            <div
              v-for="(ep, idx) in episodes"
              :key="ep.name"
              class="bangumi-episode"
              @click="play(ep)"
            >
              <span class="bangumi-episode-index">{{ idx + 1 }}</span>
              <svg-icon name="file-type-video" class="bangumi-episode-icon" color="#67c23a" />
              <span class="bangumi-episode-name" :title="ep.name">{{ ep.name }}</span>
              <span class="bangumi-episode-size">{{ fileSizeFormat(ep.size) }}</span>
            </div>
          </div>
        </template>

      </div>
    </div>

    <!-- 视频播放器（与文件页共用，数据经 fileDataStore 灌入） -->
    <video-player-dialog />
  </div>
</template>

<script setup>
import { fileSizeFormat } from '~/utils'

import useFileDataStore from '~/stores/file-data'
import useStorageConfigStore from '~/stores/storage-config'
import useVideoPlayerDialog from '~/composables/file/useVideoPlayerDialog'

import { fetchWatchFiles, fetchWatchStorageConfig } from '~/api/watch'
import { errMsg } from '~/http/watch'

const fileDataStore = useFileDataStore()
const storageConfigStore = useStorageConfigStore()
const { openDialogWithData } = useVideoPlayerDialog()

// 目录栈：[] = 白名单根（番剧列表），['言叶之庭 (2013)', 'Season 1'] = 剧集列表
const pathStack = ref([])
const items = ref([])
const loading = ref(false)
const error = ref('')

const folders = computed(() => items.value.filter((i) => i.type === 'FOLDER'))
const episodes = computed(() => items.value.filter((i) => i.type === 'FILE' && isVideo(i.name)))

const isVideo = (name) => {
  const suffix = name.substring(name.lastIndexOf('.') + 1).toLowerCase()
  return constant.fileTypeMap.video.includes(suffix)
}

/**
 * 拉取当前目录文件列表。
 * 每次都重新拉取：列表里的签名 url 有效期 30 分钟，重进目录/点刷新即自然换新。
 */
const load = async () => {
  loading.value = true
  error.value = ''
  const path = pathStack.value.length ? '/' + pathStack.value.join('/') : '/'
  try {
    const data = await fetchWatchFiles(path)
    items.value = data.files || []
    // 灌入全局文件数据：播放器的字幕匹配/上下集切换都从 fileListSource 里找
    fileDataStore.updateFileList(items.value)
  } catch (e) {
    error.value = errMsg(e)
    items.value = []
  } finally {
    loading.value = false
  }
}

const enterFolder = (folder) => {
  pathStack.value.push(folder.name)
  load()
}

// index = -1 回到根
const goTo = (index) => {
  pathStack.value = pathStack.value.slice(0, index + 1)
  load()
}

const play = (row) => {
  fileDataStore.updateCurrentClickRow(row)
  openDialogWithData(row.name)
}

onBeforeMount(() => {
  // 游客权限灌入（播放器右键菜单等据此判断：download=false → 无下载项），失败不阻塞浏览
  fetchWatchStorageConfig('/')
    .then((cfg) => storageConfigStore.updateFolderConfig(cfg))
    .catch(() => {})
  load()
})
</script>

<style scoped lang="scss">
// 复刻 file.vue 的卡片模式容器（那套样式是 scoped 的，跨页面不生效）
.zfile-index-body {
  @apply h-full;
}

.zfile-index-table-card {
  @apply w-11/12 max-w-7xl mx-auto;

  &::after {
    content: "";
    @apply top-2 h-2.5 block relative;
  }

  .z-file-view {
    @apply my-5 p-5 rounded-lg shadow-lg;
  }
}

.bangumi-page {
  @apply min-h-[300px];
}

.bangumi-toolbar {
  @apply flex items-center justify-between mb-4;

  .bangumi-crumb {
    @apply cursor-pointer;

    &:not(.is-current):hover {
      @apply text-blue-600;
    }

    &.is-current {
      @apply text-gray-700 cursor-default;
    }
  }
}

.bangumi-status {
  @apply flex flex-col items-center justify-center py-16 text-gray-400;

  .bangumi-status-icon {
    @apply w-40 h-32 mb-4;
  }

  .bangumi-status-text {
    @apply mb-4;
  }
}

// 番剧卡片网格
.bangumi-grid {
  @apply grid grid-cols-2 sm:grid-cols-3 md:grid-cols-4 lg:grid-cols-5 gap-4;
}

.bangumi-card {
  @apply flex flex-col items-center p-4 rounded-lg border border-gray-100 cursor-pointer transition-shadow;

  &:hover {
    @apply shadow-lg border-blue-100;
  }

  .bangumi-card-icon {
    @apply w-14 h-14 mb-2;
  }

  .bangumi-card-name {
    @apply w-full text-center text-sm text-gray-700 truncate;
  }
}

// 剧集列表
.bangumi-episodes {
  @apply border border-gray-100 rounded-lg overflow-hidden;
}

.bangumi-episode {
  @apply flex items-center px-4 py-3 cursor-pointer border-b border-gray-50 last:border-b-0;

  &:hover {
    @apply bg-blue-50;
  }

  .bangumi-episode-index {
    @apply w-8 text-gray-400 text-sm;
  }

  .bangumi-episode-icon {
    @apply w-6 h-6 mr-3 flex-shrink-0;
  }

  .bangumi-episode-name {
    @apply flex-1 text-gray-700 truncate;
  }

  .bangumi-episode-size {
    @apply ml-3 text-gray-400 text-sm flex-shrink-0;
  }
}
</style>

<route lang="yaml">
meta:
  layout: file
  name: 看番
</route>
