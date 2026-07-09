<template>
  <div class="chat-input-bar">
    <input
      v-model="inputText"
      placeholder="输入修改需求..."
      :disabled="generating"
      @keydown.enter="send"
    >
    <button
      class="mic-btn"
      :class="{ recording }"
      :disabled="generating"
      @mousedown="startRec"
      @mouseup="stopRec"
      @touchstart.prevent="startRec"
      @touchend.prevent="stopRec"
      title="按住说话"
    >
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="1" width="6" height="11" rx="3"/><path d="M5 10a7 7 0 0 0 14 0"/><line x1="12" y1="17" x2="12" y2="21"/><line x1="8" y1="21" x2="16" y2="21"/></svg>
    </button>
    <button class="send-btn modify-btn" :disabled="generating" @click="send" title="应用修改到当前图示">
      🎨 修改 Scene {{ activeScene > 0 ? activeScene : 1 }}
    </button>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useRecorder } from '../composables/useRecorder'

const props = defineProps<{ generating: boolean; activeScene: number }>()

const emit = defineEmits<{
  modifyScene: [message: string]
}>()

const inputText = ref('')
const { recording, startRecord, stopRecord } = useRecorder()

function send() {
  if (props.generating) return
  const msg = inputText.value.trim()
  if (!msg) return
  inputText.value = ''
  emit('modifyScene', msg)
}

function startRec() { startRecord() }
async function stopRec() {
  const text = await stopRecord()
  if (text) inputText.value = text
}
</script>
