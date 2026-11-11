<script setup lang="ts">
// 行内输入框：回车 / 失焦提交，Esc 取消。用于新建、重命名。
import { onMounted, ref } from 'vue'

const props = defineProps<{ initial?: string; placeholder?: string }>()
const emit = defineEmits<{ commit: [value: string]; cancel: [] }>()

const value = ref(props.initial ?? '')
const el = ref<HTMLInputElement>()
let done = false

onMounted(() => {
  el.value?.focus()
  el.value?.select()
})

function commit() {
  if (done) return
  done = true
  const v = value.value.trim()
  v ? emit('commit', v) : emit('cancel')
}
function cancel() {
  if (done) return
  done = true
  emit('cancel')
}
</script>

<template>
  <input
    ref="el"
    v-model="value"
    class="txt"
    maxlength="20"
    :placeholder="placeholder"
    @keydown.enter.prevent="commit"
    @keydown.esc.prevent.stop="cancel"
    @blur="commit"
    @click.stop
  />
</template>
