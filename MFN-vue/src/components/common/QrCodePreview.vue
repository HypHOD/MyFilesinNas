<template>
	<div class="relative inline-block group" v-bind="attrs">
		<el-image
			:src="props.src"
			:alt="props.alt"
			:fit="props.imgFit"
			class="block w-full h-full"
		/>
		<el-tooltip v-if="props.showDownload" content="下载二维码" placement="top">
			<span
				class="absolute top-2 right-2 inline-flex items-center justify-center w-8 h-8 rounded-full bg-white/80 backdrop-blur-sm text-blue-400 shadow ring-1 ring-blue-200/60 transition duration-200 opacity-0 scale-90 cursor-pointer group-hover:opacity-100 group-hover:scale-100 group-hover:bg-blue-50 group-hover:text-blue-500 group-hover:ring-blue-200 focus-visible:opacity-100 focus-visible:scale-100 focus-visible:bg-blue-50 focus-visible:text-blue-500 focus-visible:ring-blue-200 group-focus-within:opacity-100 group-focus-within:scale-100"
				:class="downloading ? 'pointer-events-none opacity-70' : ''"
				role="button"
				tabindex="0"
				aria-label="下载二维码"
				:aria-busy="downloading"
				@click.stop="downloadAsPng"
				@keydown.stop="handleKeydown"
			>
				<i-mdi-download class="text-base" />
			</span>
		</el-tooltip>
	</div>
</template>

<script setup>
import { ref, useAttrs } from 'vue'

defineOptions({ inheritAttrs: false })

const props = defineProps({
	src: {
		type: String,
		required: true
	},
	showDownload: {
		type: Boolean,
		default: true
	},
	filename: {
		type: String,
		default: 'qrcode.png'
	},
	alt: {
		type: String,
		default: ''
	},
	imgFit: {
		type: String,
		default: 'contain'
	}
})

const attrs = useAttrs()
const downloading = ref(false)

const handleKeydown = (event) => {
	if (event.key === 'Enter' || event.key === ' ' || event.key === 'Spacebar' || event.key === 'Space') {
		event.preventDefault()
		downloadAsPng()
	}
}

const downloadAsPng = async () => {
	if (!props.src || downloading.value) {
		return
	}
	downloading.value = true
	try {
		const image = await loadImage(props.src)
		const canvas = document.createElement('canvas')
		canvas.width = image.naturalWidth || image.width
		canvas.height = image.naturalHeight || image.height
		const ctx = canvas.getContext('2d')
		if (!ctx) {
			throw new Error('Canvas not supported')
		}
		ctx.drawImage(image, 0, 0)
		const blob = await canvasToBlob(canvas)
		const url = URL.createObjectURL(blob)
		const link = document.createElement('a')
		link.href = url
		link.download = props.filename || 'qrcode.png'
		document.body.appendChild(link)
		link.click()
		document.body.removeChild(link)
		URL.revokeObjectURL(url)
	} catch (error) {
		console.error('Failed to download QR code', error)
		if (typeof ElMessage !== 'undefined') {
			ElMessage.error('二维码下载失败，请重试')
		}
	} finally {
		downloading.value = false
	}
}

const loadImage = (src) => {
	return new Promise((resolve, reject) => {
		const img = new Image()
		img.onload = () => resolve(img)
		img.onerror = reject
		img.src = src
	})
}

const canvasToBlob = (canvas) => {
	return new Promise((resolve, reject) => {
		canvas.toBlob((blob) => {
			if (blob) {
				resolve(blob)
			} else {
				reject(new Error('Failed to convert canvas to blob'))
			}
		}, 'image/png')
	})
}
</script>
