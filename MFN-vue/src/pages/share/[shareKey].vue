<template>
	<div class="zfile-index-body">
		<template v-if="shareInvalid || !shareVerified">
			<div class="share-wrapper">

				<!-- 无效分享：左文案右插画，宽屏横排，移动端纵向堆叠 -->
				<div v-if="shareInvalid" class="share-hero-panel">
					<div class="share-hero-left">
						<h2 class="hero-title">分享链接不可用</h2>
						<p class="hero-desc">{{ shareErrorMsg || '该分享链接不存在、已过期或被删除' }}</p>
						<div class="hero-actions">
							<el-button type="primary" @click="goHome">
								返回首页
							</el-button>
						</div>
					</div>
					<div class="share-hero-right share-illustration">
						<svg-icon name="404" />
					</div>
				</div>

				<!-- 密码验证：左信息右插画 -->
				<div v-else class="share-hero-panel">
					<div class="share-hero-left">
						<h2 class="hero-title">🔗 文件分享</h2>
						<p class="hero-desc">此分享受密码保护，请输入访问密码</p>
						<el-form @submit.prevent="verifyPassword" class="password-form">
							<el-form-item>
								<el-input
									v-model="passwordInput"
									type="password"
									placeholder="请输入访问密码"
									show-password
									size="large"
									class="password-input"
									@keyup.enter="verifyPassword"
								/>
							</el-form-item>
							<el-form-item>
								<el-button
									type="primary"
									size="large"
									:loading="verifying"
									@click="verifyPassword"
									class="verify-btn"
								>
									{{ verifying ? '验证中...' : '访问' }}
								</el-button>
							</el-form-item>
						</el-form>
					</div>
					<div class="share-hero-right share-illustration">
						<svg-icon name="401" />
					</div>
				</div>
			</div>
		</template>

		<!-- 通过验证后文件列表 -->
		<div
			v-else
			:class="'zfile-index-table-' + (isMobile ? storageConfigStore.globalConfig?.mobileLayout : storageConfigStore.globalConfig?.layout)"
			ref="fileIndexBodyRef"
			@contextmenu="showFileMenu"
		>
			<table-file-view :share-mode="true" class="z-file-view" v-if="zfileSettingCache.view.type === 'table'"/>
			<card-file-view :share-mode="true" class="z-file-view" v-if="zfileSettingCache.view.type === 'card'"/>

			<!-- 右键菜单（简化版，只保留查看和下载） -->
			<share-contextmenu />

			<!-- 文本编辑器 -->
			<text-viewer-dialog />

			<!-- pdf 在线预览 -->
			<pdf-viewer-dialog />

			<!-- 视频播放器 -->
			<video-player-dialog />

			<!-- office 在线预览 -->
			<office-viewer-dialog />

			<!-- kkfileview 在线预览 -->
			<KkFileViewerDialog />

			<!-- 3d 在线预览 -->
			<three3d-preview-dialog />

			<!-- 音频播放器 -->
			<audio-player />

			<!-- 回到顶部 -->
			<back-top v-show="globalConfigStore.zfileConfig.gallery.showBackTop" />
		</div>
	</div>
</template>

<script setup>
import { isMobile } from "~/utils";
import TableFileView from "~/components/file/view/TableFileView.vue";
import CardFileView from "~/components/file/view/CardFileView.vue";

import useShareData from "~/composables/share/useShareData";
const { shareVerified, sharePassword, initShare, verifySharePassword, loadShareFiles, shareInvalid, shareErrorMsg } = useShareData();

import useStorageConfigStore from "~/stores/storage-config";
let storageConfigStore = useStorageConfigStore();

import useGlobalConfigStore from "~/stores/global-config";
let globalConfigStore = useGlobalConfigStore();

// 右键菜单相关
import useFileContextMenu from "~/composables/file/useFileContextMenu";
const { showFileMenu } = useFileContextMenu();
const fileIndexBodyRef = ref();
import useFileLongPressEvent from "~/composables/file/useFileLongPressEvent";
useFileLongPressEvent(fileIndexBodyRef);

// 文件数据相关
import useSetting from "~/composables/header/useSetting";
const { zfileSettingCache } = useSetting();

const route = useRoute();
const router = useRouter();

const passwordInput = ref('');
const verifying = ref(false);

// 初始化分享页面
onBeforeMount(async () => {
  if (route.query.pwd) passwordInput.value = String(route.query.pwd);
  await initShare();
});

// 验证密码
const verifyPassword = async () => {
	if (!passwordInput.value.trim()) {
		ElMessage.warning('请输入访问密码');
		return;
	}

	verifying.value = true;
	try {
		const verified = await verifySharePassword(passwordInput.value);
        if (verified) {
            sharePassword.value = passwordInput.value;
            shareVerified.value = true;
            // 将密码写入当前 URL 的 query，确保后续下载始终携带 password
            await router.replace({
							path: route.path,
							query: { ...(route.query || {}), pwd: passwordInput.value }
						});
            await loadShareFiles(route.query.path || '/');
        } else {
			ElMessage.error('密码错误，请重新输入');
		}
	} finally {
		verifying.value = false;
	}
};

// 监听路径变化
watch(() => route.query.path, (newPath) => {
    if (shareVerified.value) {
        loadShareFiles(newPath || '/');
    }
});

const goHome = () => window.location.href='/';
</script>

<style lang="scss" scoped>
// 通用左右分栏面板（随文件页布局宽度自适应）
.share-wrapper {
  @apply flex items-center justify-center w-full bg-gray-100;
  min-height: calc(100vh - 88px); /* 48(header)+40(footer) */
  padding-top: 40px;
  padding-bottom: 40px;
}

.share-hero-panel {
  @apply w-full max-w-7xl border-t border-t-gray-100 bg-white rounded-xl shadow-lg overflow-hidden grid grid-cols-1 md:grid-cols-2 mx-auto;
  min-height: 420px;
}

.share-hero-left {
  @apply p-6 md:p-10 flex flex-col justify-center;
}

.share-hero-right {
  @apply hidden md:flex items-center justify-center bg-gradient-to-br from-gray-50 to-gray-100;
}

.hero-title { @apply text-2xl md:text-3xl font-bold text-gray-800 mb-3; }
.hero-desc { @apply text-gray-600 mb-6; }
.hero-actions { @apply flex gap-3 mb-4; }
.hero-footnote { @apply text-sm text-gray-400 mt-2; }

.share-illustration {
  @apply p-6;
  :deep(.icon) {
    width: min(420px, 60vw);
    height: min(320px, 45vw);
    color: #94a3b8; /* slate-400 */
  }
}

// 分享密码验证页面样式
.password-form {
  .password-input { @apply w-full; }
  .verify-btn { @apply w-full md:w-auto; }
}

// 复用 file.vue 的样式
.zfile-index-body {
	@apply h-full;
}

.zfile-index-body > div:has(.zfile-table-empty) {
	@apply h-full;
}

// 分享面包屑样式
.share-breadcrumb {
	@apply px-4 py-3 bg-gray-50 border-b border-gray-200;

	.el-breadcrumb-item.is-link {
		@apply cursor-pointer;

		&:hover {
			@apply text-blue-600;
		}
	}
}

// 居中模式
.zfile-index-table-center {
	@apply w-[80%] mx-auto;
}

// 卡片模式
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
</style>

<route lang="yaml">
meta:
  layout: file
</route>