<template>
	<Contextmenu auto-ajust-placement ref="contextmenu" @show="addUnderlineToLastVisibleItem">
		<template v-if="contextMenuTargetFile">
			<div class="contextmenu-group-item">
				<ContextmenuItem v-show="storageConfigStore.permission.open"
								 @click="openRow(selectRow, true)">
					<i-mdi-folder-open-outline class="contextmenu-icon" />
					<label>打开</label>
				</ContextmenuItem>
				<ContextmenuItem v-show="storageConfigStore.permission.preview"
								 @click="openRow(selectRow, true)">
					<i-mdi-eye-outline class="contextmenu-icon" />
					<label>预览</label>
				</ContextmenuItem>
				<ContextmenuItem
					v-show="storageConfigStore.permission.download && selectStatistics.isSingleSelect"
					@click="downloadShareFile"
				>
					<i-mdi-download-outline class="contextmenu-icon" />
					<label>下载</label>
				</ContextmenuItem>
				<ContextmenuItem
					v-show="storageConfigStore.permission.copyDownloadLink"
					@click="copySelectedDownloadLink"
				>
					<i-mdi-link-plus class="contextmenu-icon" />
					<label>复制下载链接</label>
				</ContextmenuItem>
			</div>
		</template>

		<ContextmenuItem @click="reload">
			<i-mdi-reload class="contextmenu-icon" />
			<label>刷新</label>
		</ContextmenuItem>
	</Contextmenu>
</template>

<script setup>
import { Contextmenu, ContextmenuItem } from "v-contextmenu";
import useFileContextMenu from "~/composables/file/useFileContextMenu";
import useFileSelect from "~/composables/file/useFileSelect";
import useShareActions from "~/composables/file/useShareActions";
import useStorageConfigStore from "~/stores/storage-config";
const { selectRow, selectStatistics } = useFileSelect();
const { openFolder, previewFile, downloadFile, copyDownloadLink } = useShareActions();
const storageConfigStore = useStorageConfigStore();

const contextmenu = ref();
const { initContextMenu, contextMenuTargetFile } = useFileContextMenu();

onMounted(() => {
	initContextMenu(contextmenu);
});

// 打开文件/文件夹
const openRow = (row, preview = false) => {
	if (row.type === 'FOLDER') {
		openFolder(row);
	} else if (preview) {
		previewFile(row);
	}
};

// 下载分享文件
const downloadShareFile = () => {
	if (!selectRow.value) {
		ElMessage.warning('请选择要下载的文件');
		return;
	}

	if (selectRow.value.type === 'FOLDER') {
		ElMessage.warning('暂不支持下载文件夹');
		return;
	}

	try {
		downloadFile(selectRow.value);
	} catch (error) {
		console.error('下载文件失败:', error);
		ElMessage.error('下载失败，请稍后重试');
	}
};

// 复制下载链接（单个）
const copySelectedDownloadLink = async () => {
	if (!selectRow.value || selectRow.value.type !== 'FILE') {
		ElMessage.warning('请选择一个文件');
		return;
	}
	await copyDownloadLink(selectRow.value);
}

// 刷新页面
const reload = () => {
	window.location.reload();
};

const addUnderlineToLastVisibleItem = () => {
	const groups = document.querySelectorAll('.contextmenu-group-item');
	groups.forEach(group => {
		const items = group.querySelectorAll('.v-contextmenu-item');
		let lastVisibleItem = null;
		items.forEach(item => {
			if (item.style.display !== 'none') {
				lastVisibleItem = item;
			}
		});
		if (lastVisibleItem) {
			group.classList.add('contextmenu-divider');
		}
	});
};
</script>

<style scoped lang="scss">
// 右键菜单
.v-contextmenu-item {
	:deep(.v-contextmenu-inner) {
		@apply p-0;
	}

	// 文字和图标的距离
	:deep(label) {
		@apply ml-2.5;
	}

	// 图标位置修正为居中
	:deep(.contextmenu-icon) {
		@apply mb-1 inline w-4;
	}
}

.contextmenu-divider {
	@apply border-b border-gray-300 mb-2;
}
</style>