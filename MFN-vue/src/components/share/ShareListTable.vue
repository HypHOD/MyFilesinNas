<template>
	<el-form
		ref="searchFormRef"
		inline
		class="z-admin-search-from share-search-form"
		label-width="90"
		:label-position="globalConfigStore.adminSearch.labelPosition"
		:size="globalConfigStore.adminSearch.size"
		:model="filters"
	>
		<el-row class="z-admin-search-from-row" :gutter="20">
			<el-col :span="globalConfigStore.adminSearch.spanSize">
				<el-form-item label="关键词" prop="keyword">
					<el-input
						v-model.trim="filters.keyword"
						clearable
						placeholder="请输入 Share Key / 名称"
						@keyup.enter="handleSearch"
						@clear="handleSearch"
					>
						<template #prefix>
							<i-mdi-magnify class="input-prefix" />
						</template>
					</el-input>
				</el-form-item>
			</el-col>
			<el-col :span="globalConfigStore.adminSearch.spanSize">
				<el-form-item label="存储源" prop="storageKey">
					<el-select
						v-model="filters.storageKey"
						clearable
						filterable
						placeholder="全部存储源"
					>
						<el-option label="全部存储源" value="" />
						<el-option
							v-for="item in storageOptions"
							:key="item.key"
							:label="item.name"
							:value="item.key"
						/>
					</el-select>
				</el-form-item>
			</el-col>
			<el-col :span="globalConfigStore.adminSearch.spanSize">
				<el-form-item label="状态" prop="status">
					<el-select v-model="filters.status" placeholder="全部状态">
						<el-option label="全部" value="all" />
						<el-option label="有效" value="active" />
						<el-option label="已过期" value="expired" />
					</el-select>
				</el-form-item>
			</el-col>
			<el-col :span="globalConfigStore.adminSearch.spanSize">
				<el-form-item label="创建时间" prop="createDate">
					<el-date-picker-plus
						class="date-range-picker"
						v-model="filters.createDate"
						type="daterange"
						:value-format="dateValueFormat"
						:default-time="defaultTime"
						:shortcuts="shortcuts"
						range-separator="至"
						start-placeholder="开始时间"
						end-placeholder="结束时间"
						clearable
						:editable="false"
					/>
				</el-form-item>
			</el-col>
			<el-col :span="globalConfigStore.adminSearch.spanSize">
				<el-button
					type="primary"
					:loading="loading"
					:icon="MagnifyingGlassIcon"
					:size="globalConfigStore.adminSearch.size"
					@click="handleSearch"
				>
					查询
				</el-button>
				<el-button :icon="ArrowPathIcon" :size="globalConfigStore.adminSearch.size" @click="handleReset">重置</el-button>
			</el-col>
		</el-row>
	</el-form>

	<el-table-plus
		max-height="500px"
		:data="shareList"
		v-loading="loading && !firstLoadCompleted"
		border
		empty-text="暂无分享"
		scrollbar-always-on
		:size="tableSize"
	>
		<el-table-column-plus label="分享内容" min-width="360">
			<template #default="{ row }">
				<div class="share-name">
					<span class="name">{{ displayName(row) }}</span>
					<el-tag v-if="row.needPassword" size="small" type="warning">需密码</el-tag>
					<el-tag v-if="row.expired" size="small" type="danger">已过期</el-tag>
				</div>
				<div class="share-meta">
					<el-popover
						v-if="shareItemsPopoverLabel(row)"
						trigger="hover"
						placement="bottom-start"
						width="360"
					>
						<template #default>
							<div class="popover-title">包含的文件 / 文件夹</div>
							<div
								v-for="section in shareItemsSections(row)"
								:key="section.type"
								class="mt-3"
							>
								<div class="popover-subtitle">{{ section.label }}</div>
								<ul class="share-items-list">
									<li
										v-for="itemName in section.items"
										:key="`${section.type}-${itemName}`"
										class="share-items-list__item"
									>
										<span class="share-items-list__badge" :class="`is-${section.type}`">
											{{ section.badge }}
										</span>
										<span class="share-items-list__text">{{ itemName }}</span>
									</li>
								</ul>
							</div>
						</template>
						<template #reference>
							<el-tag size="small" effect="plain">{{ shareItemsPopoverLabel(row) }}</el-tag>
						</template>
					</el-popover>

					<el-tooltip :content="`复制路径: ${fullSharePath(row)}`" placement="bottom">
						<el-tag
							size="small"
							effect="plain"
							class="cursor-pointer"
							@click="copySharePath(row)"
						>
							路径：{{ pathSummary(row) }}
						</el-tag>
					</el-tooltip>

					<el-tooltip content="点击复制" placement="bottom">
						<el-tag
							size="small"
							type="info"
							effect="plain"
							class="cursor-pointer"
							@click="copyShareKey(row)"
						>
							{{ row.shareKey }}
						</el-tag>
					</el-tooltip>
				</div>
			</template>
		</el-table-column-plus>

		<el-table-column-plus v-if="isAdminMode" label="所属用户" min-width="140" align="center">
			<template #default="{ row }">
				<div class="share-owner">
					<span>{{ row.nickname || row.username || '-' }}</span>
					<span
						v-if="row.nickname && row.username && row.nickname !== row.username"
						class="share-owner__username"
					>
						({{ formatEllipsis(row.username, 10, 'middle') }})
					</span>
				</div>
			</template>
		</el-table-column-plus>

		<el-table-column-plus show-overflow-tooltip label="存储源" min-width="150" align="center">
			<template #default="{ row }">
				<span>{{ row.storageName || row.storageKey || "-" }} </span>
			</template>
		</el-table-column-plus>

		<el-table-column-plus label="有效期至" min-width="170" align="center">
			<template #header>
				<div class="expire-header">
					<span>有效期至</span>
					<el-tooltip content="清理所有已过期分享" placement="top">
						<i-mdi-broom
							class="header-action-button cursor-pointer text-gray-400 hover:text-red-500"
							@click.stop="handleDeleteExpiredShares"
						/>
					</el-tooltip>
				</div>
			</template>
			<template #default="{ row }">
				{{ displayExpire(row) }}
			</template>
		</el-table-column-plus>

		<el-table-column-plus label="统计" min-width="150" align="center">
			<template #header>
				<span>统计</span>
				<el-tooltip content="为了系统性能，这里的统计信息最多会有 5 秒的延迟" placement="top">
					<i-mdi-information-outline class="header-action-button inline ml-1 -mt-0.5" />
				</el-tooltip>
			</template>
			<template #default="{ row }">
				访问 {{ row.accessCount || 0 }} · 下载 {{ row.downloadCount || 0 }}
			</template>
		</el-table-column-plus>

		<el-table-column-plus label="创建时间" min-width="170" align="center">
			<template #default="{ row }">
				{{ displayCreate(row) }}
			</template>
		</el-table-column-plus>

		<el-table-column-plus label="操作" min-width="180" fixed="right" align="center">
			<template #default="{ row }">
				<div class="action-buttons">
					<div class="action-button-wrapper">
						<el-dropdown
							trigger="hover"
							placement="bottom"
							@command="(command) => handleCopyDropdownCommand(command, row)"
						>
							<el-button
								link
								size="small"
								class="action-button"
								@click.stop="handleCopyButtonClick(row)"
							>
								<i-mdi-content-copy />
							</el-button>
							<template #dropdown>
								<el-dropdown-menu>
									<el-dropdown-item command="copy-key">复制 Share Key</el-dropdown-item>
									<el-dropdown-item command="copy-link">复制分享链接</el-dropdown-item>
									<el-dropdown-item
										command="copy-link-password"
										v-if="row.needPassword && row.password"
									>
										复制带密码链接
									</el-dropdown-item>
								</el-dropdown-menu>
							</template>
						</el-dropdown>
					</div>
					<div class="action-button-wrapper">
						<el-tooltip content="打开分享" placement="bottom">
							<el-button link size="small" class="action-button" @click="openShare(row)">
								<i-mdi-open-in-new />
							</el-button>
						</el-tooltip>
					</div>
					<div class="action-button-wrapper">
						<el-popconfirm title="确认删除该分享？" width="180" @confirm="deleteShare(row)">
							<template #reference>
								<el-button link size="small" class="action-button">
									<i-mdi-delete-outline />
								</el-button>
							</template>
						</el-popconfirm>
					</div>
				</div>
			</template>
		</el-table-column-plus>
	</el-table-plus>

	<div class="mt-3" v-if="pagination.total > 0">
		<el-pagination
			background
			:layout="globalConfigStore.adminTable.pager.layout"
			:size="globalConfigStore.adminTable.pager.size"
			:total="pagination.total"
			:current-page="pagination.page"
			:page-size="pagination.limit"
			:page-sizes="[10, 20, 50, 100]"
			@current-change="handlePageChange"
			@size-change="handlePageSizeChange"
		/>
	</div>
</template>

<script setup>
import { computed, reactive, ref, watch } from "vue";
import { toClipboard } from "@soerenmartius/vue3-clipboard";
import { ElMessage, ElMessageBox } from "element-plus";
import { MagnifyingGlassIcon, ArrowPathIcon } from "@heroicons/vue/24/outline";

import { shortcuts, defaultTime, dateValueFormat, removeDuplicateSeparator, formatEllipsis } from "~/utils";
import { getAdminShareListReq, deleteAllExpiredSharesReq } from "~/api/admin/admin-share";
import { getUserShareListReq, deleteShareReq, deleteExpiredSharesReq } from "~/api/home/share";

import useGlobalConfigStore from "~/stores/global-config";
const globalConfigStore = useGlobalConfigStore();

const props = defineProps({
	mode: {
		type: String,
		default: "user"
	},
	storageList: {
		type: Array,
		default: () => []
	},
	activeStorageKey: {
		type: String,
		default: ""
	},
	active: {
		type: Boolean,
		default: true
	},
	autoFetch: {
		type: Boolean,
		default: true
	}
});
const emit = defineEmits(["status-change", "total-change"]);

// 计算状态
const isAdminMode = computed(() => props.mode === "admin");
const tableSize = computed(() => isAdminMode.value ? globalConfigStore.adminTable.size : undefined);
const storageOptions = computed(() => props.storageList || []);
const fetcher = computed(() => isAdminMode.value ? getAdminShareListReq : getUserShareListReq);
const shouldAutoFetch = computed(() => props.autoFetch !== false);

// 状态
const loading = ref(false);
const firstLoadCompleted = ref(false);

/**
 * 通知外部当前加载与数据完成状态。
 */
const emitStatus = () => {
	emit("status-change", { loading: loading.value, firstLoadCompleted: firstLoadCompleted.value });
};

// 表单和分页
const shareList = ref([]);
const searchFormRef = ref(null);
const pagination = reactive({
	page: 1,
	limit: 10,
	total: 0
});
const filters = reactive({
	keyword: "",
	status: "all",
	storageKey: "",
	createDate: []
});


/**
 * 重置筛选条件并可按需保留存储源。
 * @param {Object|boolean} options 允许通过布尔值或对象形式控制是否保留存储源。
 */
const resetFilters = (options = {}) => {
	const preserveStorage = typeof options === "boolean" ? options : Boolean(options?.preserveStorage);
	filters.keyword = "";
	filters.status = "all";
	filters.createDate = [];
	if (!preserveStorage) {
		filters.storageKey = "";
	}
	pagination.page = 1;
};

/**
 * 应用外部传入的存储源标识到筛选条件。
 */
const applyActiveStorageKey = () => {
	if (props.activeStorageKey) {
		filters.storageKey = props.activeStorageKey;
	}
};

/**
 * 构建分享列表查询参数。
 */
const buildQueryParams = () => {
	const params = {
		page: pagination.page,
		limit: pagination.limit,
		status: filters.status
	};

	if (filters.keyword) {
		params.keyword = filters.keyword;
	}
	if (filters.storageKey) {
		params.storageKey = filters.storageKey;
	}
	const dateRange = Array.isArray(filters.createDate) ? filters.createDate : [];
	if (dateRange.length === 2) {
		const [start, end] = dateRange;
		if (start) {
			params.createDateStart = start;
		}
		if (end) {
			params.createDateEnd = end;
		}
	}

	return params;
};

/**
 * 拉取分享列表数据，可控制是否重置页码与静默刷新。
 * @param {Object} [options={}] 控制重置页码与静默刷新的配置。
 * @param {boolean} [options.resetPage=false] 是否重置页码。
 * @param {boolean} [options.silent=false] 是否静默刷新。
 * @returns {Promise<void>} 返回一个在数据处理后完成的 Promise。
 */
const fetchShares = ({ resetPage = false, silent = false } = {}) => {
	if (!props.active) {
		return Promise.resolve();
	}

	if (loading.value && !silent) {
		return Promise.resolve();
	}

	if (resetPage) {
		pagination.page = 1;
	}

	if (!silent) {
		firstLoadCompleted.value = false;
		emitStatus();
	}

	loading.value = true;
	emitStatus();

	return fetcher.value(buildQueryParams())
		.then((res) => {
			const records = Array.isArray(res.data) ? res.data : [];
			const total = Number(res.dataCount ?? 0);

			if (records.length === 0 && total > 0 && pagination.page > 1) {
				pagination.page = Math.max(1, pagination.page - 1);
				return fetchShares({ silent: true });
			}

			shareList.value = records.map(item => ({
				...item,
				shareEntries: Array.isArray(item.shareEntries) ? item.shareEntries : []
			}));
			pagination.total = total;
			firstLoadCompleted.value = true;
			emit("total-change", total);
		})
		.finally(() => {
			loading.value = false;
			emitStatus();
		});
};

/**
 * 触发搜索并重置页码。
 */
const handleSearch = () => {
	fetchShares({ resetPage: true });
};

/**
 * 重置搜索表单并重新加载分享数据。
 */
const handleReset = () => {
	if (isAdminMode.value) {
		searchFormRef.value?.resetFields?.();
		resetFilters();
	} else {
		resetFilters({ preserveStorage: true });
		applyActiveStorageKey();
	}
	fetchShares({ resetPage: true });
};

/**
 * 切换分页页码后加载数据。
 * @param {number} page 新的页码。
 */
const handlePageChange = (page) => {
	pagination.page = page;
	fetchShares();
};

/**
 * 修改分页大小后重新加载数据。
 * @param {number} size 新的每页数量。
 */
const handlePageSizeChange = (size) => {
	pagination.limit = size;
	fetchShares({ resetPage: true });
};

// 状态联动
watch(() => filters.status, () => {
	if (isAdminMode.value || !props.active || !firstLoadCompleted.value) {
		return;
	}
	fetchShares({ resetPage: true });
});

watch(() => filters.storageKey, (value, oldValue) => {
	if (isAdminMode.value || !props.active || !firstLoadCompleted.value) {
		return;
	}
	if (value === oldValue) {
		return;
	}
	fetchShares({ resetPage: true });
});

watch(() => props.activeStorageKey, (value) => {
	if (!isAdminMode.value && props.active) {
		filters.storageKey = value || "";
	}
});

watch(() => props.active, (show) => {
	if (show) {
		resetFilters({ preserveStorage: !isAdminMode.value });
		if (!isAdminMode.value) {
			applyActiveStorageKey();
		}
		if (shouldAutoFetch.value || !firstLoadCompleted.value) {
			fetchShares({ resetPage: true });
		}
	} else {
		resetFilters();
		shareList.value = [];
		pagination.total = 0;
		firstLoadCompleted.value = false;
		emit("total-change", 0);
		emitStatus();
	}
}, { immediate: true });

/**
 * 生成用于展示分享条目悬浮提示的摘要文字。
 * @param {Object} item 分享记录。
 * @returns {string|null} 返回格式化后的内容或 null。
 */
const shareItemsPopoverLabel = (item) => {
	const sections = shareItemsSections(item);
	if (!sections.length) {
		return null;
	}
	const summary = sections
		.filter(section => section.items.length)
		.map(section => `${section.badge} ${section.items.length}`);
	return summary.join(" · ");
};

/**
 * 规范化分享路径并根据需求返回根目录占位。
 * @param {Object} item 分享记录。
 * @param {Object} [options={}] 控制是否使用根目录占位。
 * @param {boolean} [options.fallbackRoot=true] 是否在缺失路径时返回根目录符号。
 * @returns {string} 返回处理后的路径文本。
 */
const displayPath = (item, { fallbackRoot = true } = {}) => {
	if (!item.sharePath || item.sharePath === "/") {
		return fallbackRoot ? "/" : "根目录";
	}
	return removeDuplicateSeparator(item.sharePath);
};

/**
 * 推断分享名称，支持优先返回完整路径。
 * @param {Object} item 分享记录。
 * @param {boolean} preferFullPath 是否优先返回完整路径。
 * @returns {string} 返回可展示的名称。
 */
const derivePathName = (item, preferFullPath = false) => {
	const path = displayPath(item, { fallbackRoot: true });
	if (path === "/") {
		return preferFullPath ? "/" : item.shareKey;
	}
	if (preferFullPath) {
		return path;
	}
	const segments = path.split("/").filter(Boolean);
	return segments.length ? segments[segments.length - 1] : path;
};

/**
 * 将分享条目按类型拆分为分组。
 * @param {Object} item 分享记录。
 * @returns {Array} 返回包含分组信息的集合。
 */
const shareItemsSections = (item) => {
	if (!Array.isArray(item.shareEntries) || item.shareEntries.length === 0) {
		return [];
	}

	const buckets = {
		file: [],
		folder: [],
		unknown: []
	};

	item.shareEntries.forEach(entry => {
		const safeName = entry?.name;
		if (!safeName) {
			return;
		}

		if (entry?.type === "FOLDER") {
			buckets.folder.push(safeName);
			return;
		}

		if (entry?.type === "FILE") {
			buckets.file.push(safeName);
			return;
		}

		const guessed = guessShareItemType(item, safeName);
		buckets[guessed].push(safeName);
	});

	const sections = [];
	if (buckets.folder.length) {
		sections.push({ type: "folder", label: `文件夹 (${buckets.folder.length})`, badge: "文件夹", items: buckets.folder });
	}
	if (buckets.file.length) {
		sections.push({ type: "file", label: `文件 (${buckets.file.length})`, badge: "文件", items: buckets.file });
	}
	if (buckets.unknown.length) {
		sections.push({ type: "unknown", label: `未分类 (${buckets.unknown.length})`, badge: "未分类", items: buckets.unknown });
	}

	return sections;
};

/**
 * 根据条目信息推断类型。
 * @param {Object} item 分享记录。
 * @param {string} itemName 条目名称。
 * @returns {string} 返回推断出的类型标识。
 */
const guessShareItemType = (item, itemName) => {
	if (!itemName) {
		return "unknown";
	}

	if (item.shareType === "FILE") {
		return "file";
	}
	if (item.shareType === "FOLDER") {
		return "folder";
	}

	if (itemName.endsWith("/")) {
		return "folder";
	}

	if (itemName.includes(".")) {
		const ext = itemName.split(".").pop();
		if (ext && ext.length <= 8) {
			return "file";
		}
	}

	return "unknown";
};

/**
 * 生成分享名称，兼容多条目场景。
 * @param {Object} item 分享记录。
 * @returns {string} 返回适合展示的名称。
 */
const displayName = (item) => {
	if (Array.isArray(item.shareEntries) && item.shareEntries.length === 1) {
		return item.shareEntries[0]?.name;
	}
	if (Array.isArray(item.shareEntries) && item.shareEntries.length > 1) {
		return `${item.shareEntries[0]?.name} 等 ${item.shareEntries.length} 项`;
	}
	return derivePathName(item);
};

const MAX_PATH_SUMMARY_LENGTH = 12;

/**
 * 根据路径生成适用于标签展示的摘要。
 * @param {Object} item 分享记录。
 * @returns {string} 返回摘要文本。
 */
const pathSummary = (item) => {
	const fullPath = displayPath(item, { fallbackRoot: true });
	if (fullPath === "/") {
		return "根目录";
	}

	const segments = fullPath.split("/").filter(Boolean);
	if (segments.length <= 2) {
		return formatEllipsis(fullPath, MAX_PATH_SUMMARY_LENGTH, "middle");
	}

	const summary = `/${segments[0]}/…/${segments.slice(-2).join("/")}`;
	return formatEllipsis(summary, MAX_PATH_SUMMARY_LENGTH, "middle");
};

/**
 * 获取完整分享路径。
 * @param {Object} item 分享记录。
 * @returns {string} 返回完整路径。
 */
const fullSharePath = (item) => displayPath(item, { fallbackRoot: true });

/**
 * 格式化分享过期时间。
 * @param {Object} item 分享记录。
 * @returns {string} 返回过期时间描述。
 */
const displayExpire = (item) => {
	if (!item.expireDate) {
		return "永久有效";
	}
	return item.expireDate;
};

/**
 * 格式化分享创建时间。
 * @param {Object} item 分享记录。
 * @returns {string} 返回创建时间描述。
 */
const displayCreate = (item) => {
	if (!item.createDate) {
		return "-";
	}
	return item.createDate;
};

/**
 * 复制分享路径并提示结果。
 * @param {Object} item 分享记录。
 * @returns {Promise<void>} 返回复制完成后的 Promise。
 */
const copySharePath = (item) => {
	const path = displayPath(item, { fallbackRoot: true });
	return toClipboard(path).then(() => {
		ElMessage.success("分享路径已复制");
	});
};

/**
 * 复制分享标识并提示结果。
 * @param {Object} item 分享记录。
 * @returns {Promise<void>} 返回复制完成后的 Promise。
 */
const copyShareKey = (item) => {
	return toClipboard(item.shareKey).then(() => {
		ElMessage.success("Share Key 已复制");
	});
};

/**
 * 点击复制按钮时默认复制链接。
 * @param {Object} item 分享记录。
 * @returns {Promise<void>} 返回复制完成后的 Promise。
 */
const handleCopyButtonClick = (item) => {
	return copyLink(item);
};

/**
 * 处理复制下拉菜单的具体指令。
 * @param {string} command 用户选择的指令。
 * @param {Object} item 分享记录。
 * @returns {Promise<void>} 返回对应操作执行后的 Promise。
 */
const handleCopyDropdownCommand = (command, item) => {
	if (!item) {
		return Promise.resolve();
	}

	if (command === "copy-key") {
		return copyShareKey(item);
	}

	if (command === "copy-link") {
		return copyLink(item);
	}

	if (command === "copy-link-password") {
		return copyLinkWithPassword(item);
	}

	return Promise.resolve();
};

/**
 * 构建分享链接地址。
 * @param {Object} item 分享记录。
 * @returns {string} 返回分享链接。
 */
const buildShareUrl = (item) => {
	const base = window.location.origin;
	return `${base.replace(/\/$/, "")}/share/${encodeURIComponent(item.shareKey)}`;
};

/**
 * 复制分享链接并提示结果。
 * @param {Object} item 分享记录。
 * @returns {Promise<void>} 返回复制完成后的 Promise。
 */
const copyLink = (item) => {
	const url = buildShareUrl(item);
	return toClipboard(url).then(() => {
		ElMessage.success("分享链接已复制");
	});
};

/**
 * 复制带密码的分享链接。
 * @param {Object} item 分享记录。
 * @returns {Promise<void>} 返回复制完成后的 Promise。
 */
const copyLinkWithPassword = (item) => {
	if (!item.password) {
		ElMessage.warning("未获取到分享密码");
		return Promise.resolve();
	}

	const url = `${buildShareUrl(item)}?pwd=${encodeURIComponent(item.password)}`;
	return toClipboard(url).then(() => {
		ElMessage.success("带密码链接已复制");
	});
};

/**
 * 打开分享页面。
 * @param {Object} item 分享记录。
 */
const openShare = (item) => {
	const url = `${window.location.origin}/share/${encodeURIComponent(item.shareKey)}`;
	window.open(url, "_blank");
};

/**
 * 删除指定分享并刷新列表。
 * @param {Object} item 分享记录。
 * @returns {Promise<void>} 返回删除完成后的 Promise。
 */
const deleteShare = (item) => {
	return deleteShareReq(item.shareKey).then(() => {
		ElMessage.success("分享已删除");
		return fetchShares();
	});
};

/**
 * 清理所有已过期的分享记录。
 */
const cleanExpiredLoading = ref(false);
const handleDeleteExpiredShares = () => {
	if (cleanExpiredLoading.value) {
		return;
	}

	ElMessageBox.confirm("确认清理所有已过期分享？", "提示", {
		confirmButtonText: "确认清理",
		cancelButtonText: "取消",
		type: "warning"
	}).then(() => {
		cleanExpiredLoading.value = true;
		const request = isAdminMode.value ? deleteAllExpiredSharesReq : deleteExpiredSharesReq;
		return request()
			.then((res) => {
				const deletedCount = Number(res?.data ?? 0);
				ElMessage.success(`已清理 ${deletedCount} 个过期分享`);
				return fetchShares({ resetPage: false });
			});
	}).finally(() => {
		cleanExpiredLoading.value = false;
	});
};

// 对外暴露
defineExpose({
	fetchShares,
	resetFilters,
	shareList,
	pagination,
	loading,
	firstLoadCompleted
});
</script>

<style scoped lang="scss">
/* 分享名称行，展示名称与状态标记 */
.share-name {
	@apply flex items-center gap-1.5 font-semibold text-gray-800;

	/* 分享名称文本内容，处理溢出省略 */
	.name {
		@apply flex-1 min-w-0 overflow-hidden text-ellipsis whitespace-nowrap;
	}
}

/* 分享额外信息区域，显示标签与统计 */
.share-meta {
	@apply flex flex-wrap items-center gap-2 mt-1.5;
}

/* 分享条目列表容器，承载子项集合 */
.share-items-list {
	@apply m-0 list-none max-h-40 overflow-y-auto p-0;
}

/* 分享条目列表单项 */
.share-items-list__item {
	@apply text-sm py-0.5 break-words;
}

/* 分享条目标识徽标，区分类型 */
.share-items-list__badge {
	@apply inline-flex items-center justify-center min-w-[48px] px-1.5 mr-2 rounded-md text-xs bg-gray-100 text-gray-600;

	/* 文件夹徽标颜色 */
	&.is-folder {
		@apply bg-indigo-50 text-indigo-700;
	}

	/* 文件徽标颜色 */
	&.is-file {
		@apply bg-emerald-50 text-emerald-600;
	}

	/* 未识别类型徽标颜色 */
	&.is-unknown {
		@apply bg-amber-100 text-amber-700;
	}
}

/* 悬浮卡片标题文本 */
.popover-title {
	@apply font-semibold mb-2;

	/* 悬浮卡片小标题文本 */
	.popover-subtitle {
		@apply font-semibold mb-1;
	}
}

/* 所属用户列 */
.share-owner {
	/* 多行显示 */
	@apply flex flex-col;

	/* 分享者名称样式 */
	.share-owner__username {
		@apply text-xs text-gray-500;
	}
}

/* 操作按钮容器 */
.action-button-wrapper {
	@apply inline-flex;

	/* 相邻操作按钮间距 */
	& + .action-button-wrapper {
		@apply ml-3;
	}

	/* 操作列按钮图标大小 */
	button {
		@apply text-sm;
	}
}

/* 有效期列表头包含操作按钮 */
.expire-header {
	@apply flex items-center justify-center gap-1;
}

/* 表头操作按钮样式 */
.header-action-button {
	@apply ml-1 text-xs focus:outline-none focus-visible:outline-none;
}
</style>