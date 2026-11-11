<script setup lang="ts">
import { onMounted, ref, watch } from 'vue'

const props = withDefaults(defineProps<{
  src: string
  alt: string
  thumbnail?: boolean
}>(), { thumbnail: false })
const loaded = ref(false)
const failed = ref(false)
const element = ref<HTMLImageElement>()
onMounted(() => {
  // 预载图片已经解码时，首帧直接显示，避免重新闪出加载占位。
  if (element.value?.complete && element.value.naturalWidth > 0) loaded.value = true
})
watch(() => props.src, () => { loaded.value = false; failed.value = false })
</script>

<template>
  <div class="preview-image" :class="{ thumbnail }">
    <img ref="element" :key="src" :src="src" :alt="alt" :loading="thumbnail ? 'lazy' : 'eager'"
      decoding="async" :class="{ loaded }" @load="loaded = true" @error="failed = true" />
    <span v-if="!loaded" class="preview-status" role="status">
      {{ failed ? (thumbnail ? '预览失败' : '预览加载失败，请点击刷新预览') : (thumbnail ? '加载中…' : '正在加载幻灯片…') }}
    </span>
  </div>
</template>

<style scoped>
.preview-image { position: absolute; inset: 0; background: #080808; }
img { display: block; width: 100%; height: 100%; object-fit: contain; opacity: 0; }
img.loaded { opacity: 1; }
.preview-status { position: absolute; inset: 0; display: grid; place-content: center; padding: 12px; color: #b0acd6; font-size: 13px; text-align: center; }
.thumbnail .preview-status { font-size: 10px; padding: 3px; }
</style>
