import { ref } from 'vue'

const createShareDialogRef = ref()

import useFileSelect from './useFileSelect'
const { selectStatistics } = useFileSelect()

/**
 * 文件分享相关功能
 */
export default function useFileShare() {

  /**
   * 打开创建分享对话框
   */
  const openCreateShareDialog = () => {
    // 至少选择 1 个即可
    if (!selectStatistics.value.isSelected) {
      ElMessage.warning('请先选择要分享的文件或文件夹')
      return
    }

    createShareDialogRef.value?.openDialog()
  }

  /**
   * 设置创建分享对话框引用
   * @param {Object} ref - 对话框组件引用
   */
  const setCreateShareDialogRef = (ref) => {
    createShareDialogRef.value = ref.value
  }

  return {
    // 对话框相关
    openCreateShareDialog,
    setCreateShareDialogRef
  }
}