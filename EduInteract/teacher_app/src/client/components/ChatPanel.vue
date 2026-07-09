<template>
  <div id="chat-sidebar" :class="{ open: open }">
    <div class="sidebar-header">
      <span class="sidebar-header-title">AI 讲解</span>
      <div class="auto-read-wrap">
        <label class="auto-read-switch">
          <input type="checkbox" v-model="autoRead">
          <span class="auto-read-slider"></span>
        </label>
        <span>朗读</span>
      </div>
      <button class="sidebar-close-btn" @click="$emit('close')">✕</button>
    </div>
    <div class="chat-messages" ref="messagesEl">
      <div v-if="messages.length === 0" class="guide-scene-empty" style="height:80px;margin:auto;">
        输入问题开始对话
      </div>
      <template v-for="(msg, i) in messages" :key="i">
        <div class="msg-row" :class="msg.role">
          <img v-if="msg.role === 'assistant'" :src="BASE + 'teacher_explaining.svg'" class="msg-avatar" alt="AI">
          <div class="msg-bubble" :class="msg.role">
            <div v-if="msg.role === 'assistant'" v-html="renderMarkdown(msg.content)"></div>
            <template v-else>{{ msg.content }}</template>
          </div>
        </div>
        <!-- 修改图示按钮 -->
        <div
          v-if="msg.role === 'user' && hasScenes && isLastUserMsg(i)"
          class="modify-action"
        >
          <button class="btn-modify" @click="applyModify(msg.content)">
            🎨 应用修改到 Scene {{ activeScene > 0 ? activeScene : 1 }}
          </button>
        </div>
      </template>
    </div>
    <!-- Sidebar内的输入框 -->
    <div style="padding:10px 16px;border-top:1px solid var(--border);display:flex;gap:8px;align-items:center;background:#fff;">
      <input
        ref="chatInputEl"
        v-model="inputText"
        placeholder="输入问题或修改需求..."
        @keydown.enter="send"
        style="flex:1;padding:9px 14px;border:1.5px solid var(--border);border-radius:10px;font-family:inherit;font-size:.9rem;background:#fafaff;"
      >
      <button
        class="mic-btn"
        :class="{ recording }"
        @mousedown="startRec"
        @mouseup="stopRec"
        @touchstart.prevent="startRec"
        @touchend.prevent="stopRec"
      >
        <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><rect x="9" y="1" width="6" height="11" rx="3"/><path d="M5 10a7 7 0 0 0 14 0"/><line x1="12" y1="17" x2="12" y2="21"/><line x1="8" y1="21" x2="16" y2="21"/></svg>
      </button>
      <button class="send-btn" @click="send">➤</button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch, nextTick } from 'vue'
import type { ChatMessage } from '../composables/useChat'
import { useRecorder } from '../composables/useRecorder'

declare const marked: { parse: (s: string) => string }
declare const MathJax: { typesetPromise?: (el: Element[]) => Promise<void> }

const props = defineProps<{
  open: boolean
  messages: ChatMessage[]
  activeScene: number
  hasScenes: boolean
}>()

const emit = defineEmits<{
  close: []
  send: [message: string]
  modifyScene: [userRequest: string]
}>()

const inputText = ref('')
const autoRead = ref(true)
const BASE = import.meta.env.BASE_URL
const messagesEl = ref<HTMLElement | null>(null)
const chatInputEl = ref<HTMLInputElement | null>(null)
const { recording, startRecord, stopRecord } = useRecorder()

function renderMarkdown(text: string): string {
  return marked.parse(text || '')
}

function isLastUserMsg(index: number): boolean {
  for (let i = props.messages.length - 1; i >= 0; i--) {
    if (props.messages[i].role === 'user') return i === index
  }
  return false
}

function send() {
  const msg = inputText.value.trim()
  if (!msg) return
  inputText.value = ''
  emit('send', msg)
}

function applyModify(userRequest: string) {
  emit('modifyScene', userRequest)
}

function startRec() { startRecord() }
async function stopRec() {
  const text = await stopRecord()
  if (text) inputText.value = text
}

watch(() => props.messages, async () => {
  await nextTick()
  if (messagesEl.value) {
    messagesEl.value.scrollTop = messagesEl.value.scrollHeight
    const bubbles = messagesEl.value.querySelectorAll('.msg-bubble.assistant')
    if (typeof MathJax !== 'undefined' && MathJax.typesetPromise && bubbles.length) {
      MathJax.typesetPromise(Array.from(bubbles) as Element[])
    }
  }
}, { deep: true })

watch(() => props.open, (v) => {
  if (v) nextTick(() => chatInputEl.value?.focus())
})
</script>
