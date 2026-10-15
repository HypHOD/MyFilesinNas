import { toClipboard } from '@soerenmartius/vue3-clipboard'
import { concatPath, getFileType, buildShareBasePath } from '~/utils'
import { getShareFileDownloadUrlReq } from '~/api/home/share'

import useRouterData from '~/composables/useRouterData'
const { routeRef, routerRef } = useRouterData()

import useFileDataStore from '~/stores/file-data'
const { updateCurrentClickRow } = useFileDataStore()

import useFilePreview from '~/composables/file/useFilePreview'
const {
	openAudio,
	openImage,
	openOffice,
	openPdf,
	openText,
	openVideo,
	open3d,
	openKkFileView,
} = useFilePreview()

import useShareData from '~/composables/share/useShareData'
const { sharePassword } = useShareData()

export default function useShareActions() {
	const shareKey = () => routeRef.value?.params?.shareKey
	const pwd = () => sharePassword?.value || routeRef.value?.query?.pwd
	const currentPath = () => routeRef.value?.query?.path || '/'

	const buildDownloadUrl = (row) => {
		const key = shareKey()
		if (!key || !row?.name) return ''
		const fullPath = concatPath(row.path, row.name)
		return getShareFileDownloadUrlReq(key, fullPath, pwd())
	}

	const openFolder = (row) => {
		if (!row?.name) return
		const base = buildShareBasePath(shareKey())
		const cur = currentPath()
		const newPath = concatPath(cur === '/' ? '' : cur, row.name)
		routerRef.value.push({
			path: base,
			query: { ...(routeRef.value?.query || {}), path: newPath, pwd: pwd() },
		})
	}

	const previewFile = (row) => {
		const url = buildDownloadUrl(row)
		const rowWithUrl = { ...row, url }
		updateCurrentClickRow(rowWithUrl)
		const ft = getFileType(row.name)
		switch (ft) {
			case 'video':
				return openVideo()
			case 'image':
				return openImage(rowWithUrl)
			case 'text':
				return openText()
			case 'audio':
				return openAudio()
			case 'office':
				return openOffice()
			case 'pdf':
				return openPdf()
			case 'three3d':
				return open3d()
			case 'kkfileview':
				return openKkFileView(rowWithUrl)
			default:
				window.open(url, '_blank')
		}
	}

	const downloadFile = (row) => {
		const url = buildDownloadUrl(row)
		if (url) window.open(url, '_blank')
	}

	const copyDownloadLink = async (row) => {
		const url = buildDownloadUrl(row)
		if (!url) return
		await toClipboard(url)
		ElMessage.success('下载链接已复制')
	}

	return {
		openFolder,
		previewFile,
		downloadFile,
		copyDownloadLink,
	}
}