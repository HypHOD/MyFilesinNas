import { getShareInfoReq, verifySharePasswordReq, getShareFileListReq, getShareFileDownloadUrlReq } from "~/api/home/share";
import { ElMessage } from "element-plus";
import useFilePwd from "~/composables/file/useFilePwd";
import useFileDataStore from "~/stores/file-data";
import useStorageConfigStore from "~/stores/storage-config";
import useFileLoading from "~/composables/file/useFileLoading";

let singleton; // 确保全局唯一实例，避免在子组件中调用时丢失状态（如密码）

import useRouterData from "~/composables/useRouterData";
let { routerRef, routeRef } = useRouterData()

export default function useShareData() {
  if (singleton) return singleton;

  const shareKey = computed(() => routeRef.value.params.shareKey);
  const shareInfo = ref(null);
  const shareVerified = ref(false);
  const sharePassword = ref('');
  const currentPath = ref('/');
  const lastSuccessPath = ref(undefined); // 最后一次成功加载的路径
  const shareInvalid = ref(false);
  const shareErrorMsg = ref('');
  const shareSearchParam = reactive({ orderBy: '', orderDirection: '' });

  const fileDataStore = useFileDataStore();
  const { popPassword } = useFilePwd();
  const storageConfigStore = useStorageConfigStore();
  const { loading, firstLoading } = useFileLoading();

  const pushShareRoute = (queryOverrides = {}) => {
    const base = `/share/${encodeURIComponent(shareKey.value)}`;
    const nextQuery = { ...(routeRef.value.query || {}), ...queryOverrides };
		routerRef.value.push({ path: base, query: nextQuery });
  };

  const getParentPath = (p) => {
    const parts = (p || '/').split('/').filter(Boolean);
    parts.pop();
    const parent = '/' + parts.join('/');
    return parent === '//' ? '/' : parent || '/';
  }

  const revertOnCancel = (requestedPath) => {
    // 优先退回到最后一次成功加载的路径，其次退回到传入路径的上级
    const target = (lastSuccessPath.value && lastSuccessPath.value !== requestedPath)
      ? lastSuccessPath.value
      : getParentPath(requestedPath || '/');
    if ((routeRef.value.query.path || '/') !== target) {
      pushShareRoute({ path: target });
    }
  }

  const verifySharePassword = async (password) => {
    const res = await verifySharePasswordReq({ shareKey: shareKey.value, password });
    return res.data;
  }

  const loadShareFiles = async (path = '/', folderPassword) => {
    loading.value = true;
    try {
      const res = await getShareFileListReq({
        shareKey: shareKey.value,
        path: path || '/',
        password: sharePassword.value,
        folderPassword,
        orderBy: shareSearchParam.orderBy || storageConfigStore.globalConfig.defaultSortField || 'name',
        orderDirection: shareSearchParam.orderDirection || storageConfigStore.globalConfig.defaultSortOrder || 'asc'
      });

      // 列表加工：文件直链（指向分享下载接口），并在非根目录插入返回上级
      let list = (res.data.fileItemList || []).map(item => {
        if (item.type === 'FILE') {
          const full = item.path ? (item.path.endsWith('/') ? item.path + item.name : item.path + '/' + item.name) : item.name;
          return { ...item, url: getShareFileDownloadUrlReq(shareKey.value, full, sharePassword.value) };
        }
        return item;
      });

      const cur = res.data.currentPath || path || '/';
      currentPath.value = cur;
      lastSuccessPath.value = cur;

      if (cur !== '/') {
        const parentPath = res.data.parentPath || getParentPath(cur);
        const parentName = parentPath === '/' ? '/' : parentPath.split('/').filter(Boolean).pop() || '/';
        list = [{ name: parentName, path: parentPath, type: 'BACK' }, ...list];
      }
      fileDataStore.updateFileList(list);

      storageConfigStore.updateFolderConfig({
        ...storageConfigStore.folderConfig,
        permission: res.data.permission || {}
      });
      loading.value = false;
      firstLoading.value = true;

      if (res.data.shareLinkInfo) {
        shareInfo.value = res.data.shareLinkInfo;
      }
    } catch (error) {
      loading.value = false;
      const data = error?.response?.data;
      if (data?.code === constant.responseCode.INVALID_PASSWORD || data?.code === constant.responseCode.REQUIRED_PASSWORD) {
        // 目录密码：分享模式不展示“记住密码”
        popPassword({ showRemember: false, defaultValue: '' })
          .then(async ({ value }) => {
            await loadShareFiles(path, value);
          })
          .catch(() => {
            // 取消时根据情况回退
            revertOnCancel(path);
          });
      } else {
        console.error('加载分享文件失败:', error);
        ElMessage.error(data?.msg || '加载文件列表失败');
      }
    }
  }

  // 表格排序变更（分享页）
  const sortShareChangeMethod = ({ prop, order }) => {
    shareSearchParam.orderBy = prop;
    shareSearchParam.orderDirection = order === 'descending' ? 'desc' : 'asc';
    const nextPath = routeRef.value.query.path || '/';
    loadShareFiles(nextPath);
  }

  const initShare = async () => {
    // 分享信息
    try {
      const shareRes = await getShareInfoReq(shareKey.value);
      shareInfo.value = shareRes.data;
    } catch (error) {
      // 无效分享：记录状态与信息，阻止继续显示密码页
      shareInvalid.value = true;
      shareErrorMsg.value = error?.response?.data?.msg || '分享链接不存在或已失效';
      return;
    }

    // URL 中的分享密码
    const urlPassword = routeRef.value.query.pwd;
    if (urlPassword) {
      sharePassword.value = String(urlPassword);
    }

    // 记录初始 URL 的 path，以便回退时有依据（若后续成功加载会被覆盖）
    const initPath = routeRef.value.query.path || '/';
    lastSuccessPath.value = undefined; // 未成功加载前置为空

    if (!shareInfo.value.needPassword || urlPassword) {
      if (urlPassword) {
        const ok = await verifySharePassword(urlPassword);
        if (ok) {
          shareVerified.value = true;
          await loadShareFiles(initPath);
        }
      } else {
        shareVerified.value = true;
        await loadShareFiles(initPath);
      }
    }
  }

  singleton = {
    shareVerified,
    sharePassword,
    shareInvalid,
    shareErrorMsg,
    initShare,
    verifySharePassword,
    loadShareFiles,
    sortShareChangeMethod
  }
  return singleton;
}