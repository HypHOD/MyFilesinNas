<template>
	<z-dialog
		class="create-share-dialog"
		v-model="dialogVisible"
		top="5vh"
		hiddenFullBtn
		title="创建分享链接"
		:close-on-click-modal="false"
		@close="resetForm"
	>
		<template #header>
			<div class="flex items-center">
				<div>创建分享</div>
				<el-tooltip content="分享链接中的文件和目录访问范围会继承当前用户的权限设置，且会随权限调整即时生效。">
					<i-mdi-information-outline class="inline w-4 text-gray-500 ml-1" />
				</el-tooltip>
			</div>
		</template>
		<div class="dialog-body-scroll">
			<el-form ref="formRef" :model="shareForm" :rules="rules">
				<el-form-item label="分享文件">
					<div class="share-file-info">
						<template v-if="shareFiles.length <= 1">
							<div class="single-line">
								<span class="file-name" :title="shareFiles[0]?.name">{{ shareFiles[0]?.name }}</span>
								<el-tag :type="shareFiles[0]?.type === 'FOLDER' ? 'success' : 'primary'" size="small">
									{{ shareFiles[0]?.type === 'FOLDER' ? '文件夹' : '文件' }}
								</el-tag>
							</div>
						</template>
						<template v-else>
							<div class="file-selected-header">
								<el-tag type="info" effect="plain">已选 {{ shareFiles.length }} 个项目</el-tag>
							</div>
							<div class="file-list">
								<div class="file-item" v-for="(item, idx) in shareFiles" :key="idx">
									<span class="file-name" :title="item.name">{{ item.name }}</span>
									<el-tag class="file-type-tag" :type="item.type === 'FOLDER' ? 'success' : 'primary'" size="small">
										{{ item.type === 'FOLDER' ? '文件夹' : '文件' }}
									</el-tag>
								</div>
							</div>
						</template>
					</div>
				</el-form-item>

				<el-form-item v-if="storageConfigStore.permission.customShareKey" label="分享 Key" prop="shareKey">
					<el-input
						v-model="shareForm.shareKey"
						placeholder="留空系统自动生成"
						clearable
					/>
				</el-form-item>

				<el-form-item label="访问密码" prop="password">
					<el-input
						v-model="shareForm.password"
						placeholder="留空为无密码访问"
						show-password
						clearable
					/>
				</el-form-item>

				<el-form-item label="有效期" prop="expirationTime">
					<el-select v-model="shareForm.expirationType" @change="handleExpirationChange">
						<el-option label="永久有效" value="never" />
						<el-option label="7天后过期" value="7d" />
						<el-option label="30天后过期" value="30d" />
						<el-option label="自定义" value="custom" />
					</el-select>

					<el-date-picker
						v-if="shareForm.expirationType === 'custom'"
						v-model="shareForm.expireDate"
						type="datetime"
						placeholder="选择过期时间"
						:disabled-date="disablePastDates"
						class="mt-2 w-full"
					/>
				</el-form-item>

				<el-form-item v-if="shareResult" label="分享链接">
					<el-input
						:value="shareResult.shareUrl"
						readonly
					>
						<template #append>
							<el-button @click="copyShareUrl" type="primary" :icon="ClipboardDocumentListIcon" />
						</template>
					</el-input>

					<el-button class="mt-2" @click="openShareUrl" size="small" type="success" :icon="LinkIcon">
						打开链接
					</el-button>
				</el-form-item>
			</el-form>
		</div>

		<template #footer>
			<span class="dialog-footer">
				<el-button @click="closeDialog">取消</el-button>
				<el-button
					v-if="!shareResult"
					type="primary"
					@click="createShare"
					:loading="creating"
				>
					{{ creating ? '创建中...' : '创建分享' }}
				</el-button>
				<el-button
					v-else
					type="primary"
					@click="closeDialog"
				>
					完成
				</el-button>
			</span>
		</template>

	</z-dialog>
</template>

<script setup>
import { toClipboard } from "@soerenmartius/vue3-clipboard";
import { formatLocalDateTime, disablePastDates } from "~/utils";
import { ClipboardDocumentListIcon, LinkIcon } from "@heroicons/vue/24/solid";

import { createShareLinkReq } from "~/api/home/share";

import useRouterData from "~/composables/useRouterData";
let { storageKey, currentPath } = useRouterData()

import useFileSelect from "~/composables/file/useFileSelect";
const { selectRows } = useFileSelect();

import useStorageConfigStore from "~/stores/storage-config";
let storageConfigStore = useStorageConfigStore();

// 当前分享的文件
const shareFiles = computed(() => Array.isArray(selectRows.value) ? selectRows.value : []);

// 对话框状态
const dialogVisible = ref(false);
const creating = ref(false);

// 表单数据与验证规则
const formRef = ref();
const shareForm = ref({
	shareKey: null,
	password: '',
	expirationType: 'never',
	expireDate: null
});
const rules = {
	shareKey: [
		{ pattern: /^[a-zA-Z0-9_-]{3,8}$/, message: '只能包含字母、数字、下划线和短横线，长度为 3-8 位', trigger: ['change', 'blur'] }
	],
	password: [
		{ min: 4, max: 20, message: '密码长度在 4 到 20 个字符', trigger: ['change', 'blur'] }
	]
};

// 处理过期时间变化
const handleExpirationChange = (value) => {
	if (value === 'never') {
		shareForm.value.expireDate = null;
	} else if (value === '7d') {
		const date = new Date();
		date.setDate(date.getDate() + 7);
		shareForm.value.expireDate = date;
	} else if (value === '30d') {
		const date = new Date();
		date.setDate(date.getDate() + 30);
		shareForm.value.expireDate = date;
	}
};

// 分享结果
const shareResult = ref(null);
const createShare = () => {
	// 组装分享参数（支持多选与类型识别）
	const entries = shareFiles.value.map(item => ({
		name: item.name,
		type: item.type === 'FOLDER' ? 'FOLDER' : 'FILE'
	}));
	const isMulti = entries.length > 1;
	const singleType = !isMulti ? (entries[0]?.type || 'FILE') : null; // FILE / FOLDER
	const params = {
		storageKey: storageKey.value,
		sharePath: currentPath.value || '/',
		shareEntries: entries,
		shareType: isMulti ? 'MULTIPLE' : (singleType === 'FOLDER' ? 'FOLDER' : 'FILE'),
		password: shareForm.value.password || null,
		expireDate: shareForm.value.expireDate ? formatLocalDateTime(shareForm.value.expireDate) : null,
		shareKey: shareForm.value.shareKey || null
	};

	formRef.value.validate((valid) => {
		if (valid) {
			creating.value = true;
			createShareLinkReq(params).then((res) => {
				ElMessage.success('分享链接创建成功！');
				// 构建完整的分享链接URL
				const baseUrl = window.location.origin;
				const shareUrl = `${baseUrl}/share/${res.data.shareKey}`;

				shareResult.value = {
					...res.data,
					shareUrl: shareForm.value.password
						? `${shareUrl}?pwd=${shareForm.value.password}`
						: shareUrl
				};
			}).finally(() => {
				creating.value = false;
			});
		}
	})
};

// 复制分享链接
const copyShareUrl = async () => {
	try {
		await toClipboard(shareResult.value.shareUrl);
		ElMessage.success('分享链接已复制到剪贴板');
	} catch (error) {
		console.error('复制失败:', error);
		ElMessage.error('复制失败，请手动复制');
	}
};

// 打开分享链接
const openShareUrl = () => {
	window.open(shareResult.value.shareUrl, '_blank');
};

// 重置表单
const resetForm = () => {
	shareForm.value = {
		password: '',
		expirationType: 'never',
		expireDate: null
	};
	shareResult.value = null;
	formRef.value?.resetFields();
	dialogVisible.value = false;
};

// 打开对话框
const openDialog = () => {
	if (!shareFiles.value || shareFiles.value.length === 0) {
		ElMessage.warning('请先选择要分享的文件或文件夹');
		return;
	}

	resetForm();
	dialogVisible.value = true;
};

// 关闭对话框
const closeDialog = () => {
	dialogVisible.value = false;
};

// 暴露方法给父组件
defineExpose({
	openDialog
});
</script>

<style lang="scss" scoped>
.create-share-dialog {
	:deep(.el-dialog) {
		@apply w-[96%] max-w-[700px] sm:w-[92%] md:w-4/5 lg:w-[700px];
	}

	:deep(.el-form-item__label) {
		@apply w-[70px] min-w-[70px] sm:w-[80px] sm:min-w-[80px] md:w-[100px] md:min-w-[100px];
	}
}

.share-file-info {
	@apply flex flex-col gap-2 p-3 bg-gray-50 rounded-lg w-full;
	box-sizing: border-box;

	.file-selected-header {
		@apply mb-1;
	}

	.file-list {
		@apply w-full mt-1 p-2 bg-white border border-gray-200 rounded;
		max-height: min(40vh, 320px);
		overflow-y: auto;
		overflow-x: hidden;
		box-sizing: border-box;
	}

	.file-item {
		display: grid;
		grid-template-columns: 1fr auto;
		align-items: center;
		column-gap: 12px;
		padding-top: 4px;
		padding-bottom: 4px;
		min-width: 0; /* 允许子项收缩防止溢出 */
	}

	.file-icon {
		@apply text-lg;
	}

	.file-name {
		@apply flex-1 font-medium;
		min-width: 0;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.file-type-tag {
		@apply shrink-0 whitespace-nowrap;
	}

	/* 单选时，名称与类型同一行展示 */
	.single-line {
		@apply flex items-center gap-2 w-full;
	}
}

// 弹窗内容区域滚动
.dialog-body-scroll {
	margin-top: 16px;
	max-height: min(80vh, 720px);
	overflow-y: auto;
}
</style>