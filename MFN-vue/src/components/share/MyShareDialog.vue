<template>
	<div class="zfile-my-share-dialog-wrapper">
		<z-dialog
			v-model="visibleProxy"
			top="5vh"
			:show-footer="false"
			destroy-on-close
		>
			<template #header>
				<div class="dialog-title">
					<span>我的分享</span>
					<el-tag v-if="status.firstLoadCompleted && !status.loading" size="small" type="info">{{ total }}</el-tag>
				</div>
			</template>

			<ShareListTable
				ref="shareTableRef"
				mode="user"
				:storage-list="storageOptions"
				:active-storage-key="props.activeStorageKey"
				:active="visibleProxy"
				@status-change="handleStatusChange"
				@total-change="handleTotalChange"
			/>
		</z-dialog>
	</div>
</template>

<script setup>
import { computed, reactive, ref } from "vue";
import ShareListTable from "~/components/share/ShareListTable.vue";

const props = defineProps({
	visible: {
		type: Boolean,
		default: false
	},
	storageList: {
		type: Array,
		default: () => []
	},
	activeStorageKey: {
		type: String,
		default: ""
	}
});
const storageOptions = computed(() => props.storageList || []);

const shareTableRef = ref(null);
const emit = defineEmits(["update:visible"]);
const visibleProxy = computed({
	get: () => props.visible,
	set: (value) => emit("update:visible", value)
});


const status = reactive({
	loading: false,
	firstLoadCompleted: false
});
const handleStatusChange = (value) => {
	status.loading = Boolean(value?.loading);
	status.firstLoadCompleted = Boolean(value?.firstLoadCompleted);
};

const total = ref(0);
const handleTotalChange = (value) => {
	total.value = Number(value ?? 0);
};

defineExpose({
	refreshShares: () => shareTableRef.value?.fetchShares(),
	resetShares: () => shareTableRef.value?.resetFilters()
});
</script>

<style scoped lang="scss">

.zfile-my-share-dialog-wrapper {
	text-align: initial; // 避免受到 dialog 外层样式影响

	:deep(.el-overlay-dialog) {
		@apply overflow-hidden;
	}

	:deep(.el-dialog) {
		@apply w-11/12 sm:w-5/6 lg:w-3/4;

		&.is-fullscreen {
			@apply w-full h-full;
		}
	}

	:deep(.el-dialog__body) {
		@apply mt-4 max-h-[80vh] md:max-h-[90vh] overflow-x-hidden overflow-y-auto;
	}
}

.dialog-title {
	display: flex;
	align-items: center;
	gap: 8px;
	font-size: 16px;
	font-weight: 600;
}
</style>