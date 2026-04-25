<template>
  <div class="topbar-section" :class="{ collapsed }">
    <div class="topbar-collapse-toggle" @click="collapsed = !collapsed">
      <span class="collapse-label">{{ collapsed ? '展开输入区' : '收起输入区' }}</span>
      <span class="collapse-arrow" :class="{ up: !collapsed }">▼</span>
    </div>
    <template v-if="!collapsed">
      <textarea
        :value="modelValue"
        @input="onInput"
        placeholder="粘贴或输入题目文字...（可直接 Ctrl+V 粘贴截图）"
      ></textarea>
      <div class="topbar-row">
        <label class="btn btn-secondary" style="cursor:pointer;margin:0;">
          📷 拍照识别题目
          <input type="file" accept="image/*" @change="onFileUpload" style="display:none">
        </label>
        <span class="status" :class="{ ok: statusClass === 'ok', err: statusClass === 'err' }">{{ statusText }}</span>
      </div>
      <div class="topbar-row">
        <button class="btn btn-primary" :disabled="disabled || !modelValue.trim() || canContinue" @click="$emit('generate')">
          生成图示
        </button>
        <button
          v-if="canContinue"
          class="btn btn-secondary"
          :disabled="disabled"
          @click="$emit('continue')"
        >
          继续生成
        </button>
      </div>
    </template>
  </div>
</template>

<script setup lang="ts">
import { ref, onMounted, onUnmounted } from 'vue'
import { apiFetch } from '../utils/api'

const props = defineProps<{
  modelValue: string
  disabled: boolean
  canContinue: boolean
  setStatus: (msg: string) => void
}>()

const emit = defineEmits<{
  'update:modelValue': [value: string]
  'update:image': [value: string]
  generate: []
  continue: []
}>()

const collapsed = ref(false)
const statusText = ref('')
const statusClass = ref('')

function onInput(e: Event) {
  emit('update:modelValue', (e.target as HTMLTextAreaElement).value)
}

async function onFileUpload(e: Event) {
  const input = e.target as HTMLInputElement
  if (!input.files?.[0]) return
  await ocrFile(input.files[0])
  input.value = ''
}

function onPaste(e: ClipboardEvent) {
  const cd = e.clipboardData
  if (!cd) return
  let file: File | null = null
  if (cd.files && cd.files.length) {
    for (let i = 0; i < cd.files.length; i++) {
      if (cd.files[i].type.startsWith('image/')) { file = cd.files[i]; break }
    }
  }
  if (!file && cd.items) {
    for (let i = 0; i < cd.items.length; i++) {
      if (cd.items[i].type.startsWith('image/')) { file = cd.items[i].getAsFile(); break }
    }
  }
  if (file) {
    e.preventDefault()
    e.stopPropagation()
    ocrFile(file)
  }
}

async function ocrFile(file: File) {
  statusText.value = '正在识别图片…'
  statusClass.value = ''
  props.setStatus('正在识别图片…')
  const b64 = await fileToBase64(file)
  try {
    const resp = await apiFetch('api/ocr', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ image: b64 }),
    })
    const data = await resp.json()
    if (data.error) {
      statusText.value = 'OCR 失败: ' + data.error
      statusClass.value = 'err'
      props.setStatus('OCR 失败')
      return
    }
    emit('update:modelValue', data.text)
    emit('update:image', b64)
    statusText.value = '识别完成'
    statusClass.value = 'ok'
    props.setStatus('识别完成')
  } catch {
    statusText.value = 'OCR 请求失败'
    statusClass.value = 'err'
    props.setStatus('OCR 请求失败')
  }
}

function fileToBase64(file: File): Promise<string> {
  return new Promise(resolve => {
    const reader = new FileReader()
    reader.onload = () => resolve((reader.result as string).split(',')[1])
    reader.readAsDataURL(file)
  })
}

onMounted(() => document.addEventListener('paste', onPaste, true))
onUnmounted(() => document.removeEventListener('paste', onPaste, true))
</script>
