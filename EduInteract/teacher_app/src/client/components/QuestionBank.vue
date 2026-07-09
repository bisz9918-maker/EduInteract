<template>
  <div v-if="open" class="bank-overlay" @click.self="$emit('close')">
    <div class="bank-panel">
      <div class="bank-header">
        <span class="bank-title">题库</span>
        <button class="sidebar-close-btn" @click="$emit('close')">✕</button>
      </div>
      <div class="bank-body">
        <div v-if="loading" class="bank-loading">加载中…</div>
        <div v-else-if="items.length === 0" class="bank-empty">暂无保存的题目</div>
        <div
          v-for="item in items"
          :key="item.id"
          class="bank-item"
          @click="onSelect(item.id)"
        >
          <div class="bank-item-text">{{ truncate(item.problemText, 80) }}</div>
          <div class="bank-item-meta">
            <span>{{ formatTime(item.timestamp) }}</span>
            <span>{{ item.sceneCount }} 个图示</span>
            <span class="bank-item-status" :class="item.completed ? 'done' : 'pending'">
              {{ item.completed ? '✓ 已完成' : '未完成' }}
            </span>
            <button class="bank-item-del" @click.stop="onDelete(item.id)">删除</button>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { apiFetch } from '../utils/api'

interface BankListItem {
  id: string
  timestamp: number
  problemText: string
  topic: string
  sceneCount: number
  completed: boolean
}

const props = defineProps<{ open: boolean }>()
const emit = defineEmits<{
  close: []
  restore: [data: any]
  continue: [data: any]
}>()

const items = ref<BankListItem[]>([])
const loading = ref(false)

watch(() => props.open, async (v) => {
  if (!v) return
  loading.value = true
  try {
    const resp = await apiFetch('api/bank/list')
    items.value = await resp.json()
  } catch {
    items.value = []
  }
  loading.value = false
})

async function onSelect(id: string) {
  const item = items.value.find(i => i.id === id)
  try {
    const resp = await apiFetch(`api/bank/${id}`)
    const data = await resp.json()
    if (item?.completed) {
      emit('restore', data)
    } else {
      emit('continue', data)
    }
    emit('close')
  } catch { /* ignore */ }
}

async function onDelete(id: string) {
  if (!confirm('确定删除该题目？')) return
  try {
    await apiFetch(`api/bank/${id}`, { method: 'DELETE' })
    items.value = items.value.filter(i => i.id !== id)
  } catch { /* ignore */ }
}

function truncate(s: string, max: number): string {
  return s.length > max ? s.slice(0, max) + '…' : s
}

function formatTime(ts: number): string {
  const d = new Date(ts)
  return `${d.getMonth() + 1}/${d.getDate()} ${d.getHours()}:${String(d.getMinutes()).padStart(2, '0')}`
}
</script>
