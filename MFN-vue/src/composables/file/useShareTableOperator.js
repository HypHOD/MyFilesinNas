import { concatPath, buildShareBasePath } from "~/utils";
import useRouterData from "~/composables/useRouterData";
import { buildTableOperator } from "~/composables/file/useTableOperator";

import useFileDataStore from "~/stores/file-data";
const fileDataStore = useFileDataStore();

import useFileContextMenu from "~/composables/file/useFileContextMenu";
const { contextMenuTargetFile, contextMenuTargetBlank } = useFileContextMenu();

import useShareActions from "~/composables/file/useShareActions";
const { previewFile, downloadFile } = useShareActions();

import useFileSelect from "~/composables/file/useFileSelect";
const { clearSelection } = useFileSelect();

import useShareData from "~/composables/share/useShareData";
const { sharePassword } = useShareData();

import useStorageConfigStore from "~/stores/storage-config";
const storageConfigStore = useStorageConfigStore();

export default function useShareTableOperator() {
  const { routeRef, routerRef } = useRouterData();
  const shareKey = computed(() => routeRef.value?.params?.shareKey);

  const getCurrentPath = () => {
    return routeRef.value?.query?.path || '/';
  }

  const openRow = (row) => {
    if (!row?.name) return;

    // 当右键菜单打开时，双击不触发打开动作，保持与文件页一致
    if (contextMenuTargetFile.value === true || contextMenuTargetBlank.value === true) {
      return;
    }

    const pwd = sharePassword?.value || routeRef.value?.query?.pwd;
    const currentPath = getCurrentPath();

    if (row.type === 'FOLDER') {
      const newPath = concatPath(currentPath === '/' ? '' : currentPath, row.name);
      routerRef.value.push({ path: buildShareBasePath(shareKey.value), query: { ...(routeRef.value?.query || {}), path: newPath, pwd } });
      return;
    }

    if (row.type === 'BACK') {
      const parts = (currentPath || '/').split('/').filter(Boolean);
      parts.pop();
      const parentPath = '/' + parts.join('/');
      routerRef.value.push({ path: buildShareBasePath(shareKey.value), query: { ...(routeRef.value?.query || {}), path: parentPath === '//' ? '/' : parentPath, pwd } });
      return;
    }

    // 文件：遵循主站逻辑，先尝试预览，权限不足时回退为下载
    const permissions = storageConfigStore.folderConfig?.permission || {};
    const canPreviewType = row.preview === true || !!row.fileType; // fileList getter 会填充
    const allowPreview = permissions.preview;
    const allowDownload = permissions.download;

    if (!allowPreview && !allowDownload) {
      return;
    }

    fileDataStore.updateCurrentClickRow(row);

    let acted = false;
    if (canPreviewType && allowPreview) {
      previewFile(row);
      acted = true;
    } else if (allowDownload) {
      downloadFile(row);
      acted = true;
    }

    if (acted) {
      clearSelection();
    }
  }

  // 复用通用表格行为（选择、拖拽、hover、双击），仅替换 openRow
  return buildTableOperator(openRow);
}