<template>
	<div>
		<admin-form-header hide-bottom-border>
			<template #title>
				<div class="header-title">
					<span class="mr-2">分享列表</span>
					<el-tag v-if="status.firstLoadCompleted && !status.loading" type="info" size="small">{{ total }}</el-tag>
				</div>
			</template>
		</admin-form-header>

		<ShareListTable
			ref="shareTableRef"
			mode="admin"
			:storage-list="storageOptions"
			@status-change="handleStatusChange"
			@total-change="handleTotalChange"
		/>
	</div>
</template>

<script setup>
import { computed, onMounted, reactive, ref } from "vue";
import ShareListTable from "~/components/share/ShareListTable.vue";
import { loadStorageListReq } from "~/api/admin/admin-storage";

const shareTableRef = ref(null);

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

const storageList = ref([]);
const storageOptions = computed(() => storageList.value || []);
const fetchStorageList = () => {
	loadStorageListReq().then((response) => {
		storageList.value = Array.isArray(response?.data) ? response.data : [];
	});
};

onMounted(() => {
	fetchStorageList();
});
</script>

<route lang="yaml">
meta:
  layout: admin
  name: 分享列表
</route>