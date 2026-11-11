<script setup lang="ts">
import { computed } from 'vue'
import { highlightParts } from '@/Common/Format'

const props = defineProps<{ text: string; tokens: string[] }>()
const parts = computed(() => highlightParts(props.text, props.tokens))
</script>

<template>
  <template v-for="(p, i) in parts" :key="i"><mark v-if="p.hit">{{ p.text }}</mark><template v-else>{{ p.text }}</template></template>
</template>
