<template>
  <!-- Overlay mask -->
  <Teleport to="body">
    <div v-if="open" class="history-mask" @click="$emit('close')" />

    <div class="history-drawer" :class="{ open }">
      <!-- Header -->
      <div class="history-header">
        <span class="history-title">场景修改历史</span>
        <button class="history-close" @click="$emit('close')">✕</button>
      </div>

      <!-- Body -->
      <div class="history-body">
        <div v-if="!sceneHistories.length" class="history-empty">
          暂无修改记录
        </div>

        <template v-for="h in sceneHistories" :key="h.sceneNum">
          <!-- Scene group header -->
          <div
            class="scene-group-header"
            @click="toggleGroup(h.sceneNum)"
          >
            <span class="scene-group-label">Scene {{ h.sceneNum }}</span>
            <span class="scene-group-count">{{ h.snapshots.length }} 个版本</span>
            <span class="scene-group-arrow" :class="{ expanded: expandedGroups.has(h.sceneNum) }">▸</span>
          </div>

          <!-- Snapshots timeline (visible when group is expanded) -->
          <div v-if="expandedGroups.has(h.sceneNum)" class="snapshot-list">
            <div
              v-for="(snap, idx) in h.snapshots"
              :key="idx"
              class="snapshot-item"
              :class="{ selected: selected?.sceneNum === h.sceneNum && selected?.idx === idx }"
              @click="selectSnap(h.sceneNum, idx, snap)"
            >
              <!-- Timeline dot + line -->
              <div class="timeline-col">
                <div class="timeline-dot" :class="{ first: idx === 0 }"></div>
                <div v-if="idx < h.snapshots.length - 1" class="timeline-line"></div>
              </div>

              <!-- Content -->
              <div class="snapshot-content">
                <div class="snapshot-meta">
                  <span class="snapshot-index">v{{ idx + 1 }}</span>
                  <span class="snapshot-time">{{ formatTime(snap.timestamp) }}</span>
                  <span v-if="idx === h.currentIdx" class="snapshot-badge current">当前</span>
                </div>
                <div class="snapshot-request">{{ snap.request }}</div>
              </div>
            </div>
          </div>
        </template>
      </div>

      <!-- Preview pane -->
      <div v-if="selected" class="history-preview">
        <div class="preview-header">
          <span>Scene {{ selected.sceneNum }} · v{{ selected.idx + 1 }} 预览</span>
          <button
            class="restore-btn"
            :disabled="isCurrentVersion"
            @click="onRestore"
          >
            {{ isCurrentVersion ? '当前版本' : '恢复此版本' }}
          </button>
        </div>
        <iframe
          :src="previewUrl"
          sandbox="allow-scripts allow-same-origin"
          class="preview-iframe"
        />
      </div>
    </div>
  </Teleport>
</template>

<script setup lang="ts">
import { ref, computed } from 'vue'
import { apiUrl } from '../utils/api'
import type { SceneHistory, SceneSnapshot } from '../composables/useGenerate'

const props = defineProps<{
  open: boolean
  sceneHistories: SceneHistory[]
}>()

const emit = defineEmits<{
  close: []
  restore: [sceneNum: number, url: string, request?: string]
}>()

// which groups are expanded
const expandedGroups = ref<Set<number>>(new Set())

function toggleGroup(num: number) {
  if (expandedGroups.value.has(num)) {
    expandedGroups.value.delete(num)
  } else {
    expandedGroups.value.add(num)
    // auto-select the latest snapshot of this group when first opened
    const h = props.sceneHistories.find(x => x.sceneNum === num)
    if (h && h.snapshots.length) {
      const idx = h.snapshots.length - 1
      selectSnap(num, idx, h.snapshots[idx])
    }
  }
}

// selected snapshot for preview
const selected = ref<{ sceneNum: number; idx: number; snap: SceneSnapshot } | null>(null)

function selectSnap(sceneNum: number, idx: number, snap: SceneSnapshot) {
  selected.value = { sceneNum, idx, snap }
}

const previewUrl = computed(() => {
  if (!selected.value) return ''
  const d = selected.value.snap.timestamp;
  const ts = d instanceof Date ? d.getTime() : new Date(d).getTime();
  return apiUrl(selected.value.snap.url) + '?t=' + ts
})

const isCurrentVersion = computed(() => {
  if (!selected.value) return false
  const h = props.sceneHistories.find(x => x.sceneNum === selected.value!.sceneNum)
  if (!h) return false
  return selected.value.idx === h.currentIdx
})

function onRestore() {
  if (!selected.value) return
  emit('restore', selected.value.sceneNum, selected.value.snap.url, '恢复旧版本')
}

function formatTime(d: Date) {
  const date = typeof d === 'string' ? new Date(d) : d;
  return date.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit', second: '2-digit' })
}
</script>

<style scoped>
/* Mask */
.history-mask {
  position: fixed;
  inset: 0;
  background: rgba(0, 0, 0, 0.35);
  z-index: 1000;
}

/* Drawer */
.history-drawer {
  position: fixed;
  top: 0;
  right: 0;
  width: 900px;
  height: 100dvh;
  background: #ffffff;
  border-left: 1px solid #e5e5e5;
  display: flex;
  flex-direction: column;
  transform: translateX(100%);
  transition: transform 0.28s ease;
  z-index: 1001;
  overflow: hidden;
}
.history-drawer.open {
  transform: translateX(0);
}

/* Header */
.history-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 16px 18px;
  border-bottom: 1px solid #e5e5e5;
  flex-shrink: 0;
}
.history-title {
  font-size: 15px;
  font-weight: 500;
  color: var(--color-text-primary);
}
.history-close {
  background: none;
  border: none;
  cursor: pointer;
  font-size: 16px;
  color: var(--color-text-secondary);
  padding: 2px 6px;
  border-radius: 4px;
}
.history-close:hover {
  background: var(--color-background-secondary);
}

/* Body (scrollable list) */
.history-body {
  flex: 1;
  overflow-y: auto;
  padding: 8px 0;
  min-height: 0;
}
.history-empty {
  padding: 40px 20px;
  text-align: center;
  color: var(--color-text-tertiary);
  font-size: 14px;
}

/* Scene group */
.scene-group-header {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 10px 18px;
  cursor: pointer;
  user-select: none;
}
.scene-group-header:hover {
  background: #f5f5f5;
}
.scene-group-label {
  font-size: 14px;
  font-weight: 500;
  color: var(--color-text-primary);
}
.scene-group-count {
  font-size: 12px;
  color: var(--color-text-tertiary);
  flex: 1;
}
.scene-group-arrow {
  font-size: 12px;
  color: var(--color-text-tertiary);
  transition: transform 0.2s;
  display: inline-block;
}
.scene-group-arrow.expanded {
  transform: rotate(90deg);
}

/* Snapshot timeline */
.snapshot-list {
  padding: 0 18px 8px 18px;
}
.snapshot-item {
  display: flex;
  gap: 12px;
  cursor: pointer;
  border-radius: 8px;
  padding: 6px 8px;
  margin-bottom: 2px;
}
.snapshot-item:hover {
  background: #f5f5f5;
}
.snapshot-item.selected {
  background: #e6f2ff;
}

/* Timeline column */
.timeline-col {
  display: flex;
  flex-direction: column;
  align-items: center;
  padding-top: 4px;
  width: 12px;
  flex-shrink: 0;
}
.timeline-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--color-border-primary);
  flex-shrink: 0;
}
.timeline-dot.first {
  background: var(--color-text-info);
}
.timeline-line {
  flex: 1;
  width: 1px;
  background: var(--color-border-tertiary);
  margin-top: 3px;
  min-height: 16px;
}

/* Snapshot content */
.snapshot-content {
  flex: 1;
  min-width: 0;
}
.snapshot-meta {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 2px;
}
.snapshot-index {
  font-size: 11px;
  font-weight: 500;
  color: var(--color-text-secondary);
  background: var(--color-background-secondary);
  border-radius: 4px;
  padding: 1px 5px;
}
.snapshot-time {
  font-size: 11px;
  color: var(--color-text-tertiary);
}
.snapshot-badge {
  font-size: 11px;
  border-radius: 4px;
  padding: 1px 6px;
}
.snapshot-badge.current {
  background: var(--color-background-success);
  color: var(--color-text-success);
}
.snapshot-request {
  font-size: 13px;
  color: var(--color-text-primary);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

/* Preview pane */
.history-preview {
  flex-shrink: 0;
  border-top: 1px solid #e5e5e5;
  display: flex;
  flex-direction: column;
  height: 900px;
}
.preview-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 14px;
  font-size: 12px;
  color: var(--color-text-secondary);
  border-bottom: 1px solid var(--color-border-tertiary);
  flex-shrink: 0;
}
.restore-btn {
  font-size: 12px;
  padding: 4px 12px;
  border-radius: 6px;
  border: 1px solid var(--color-border-secondary);
  background: var(--color-background-primary);
  color: var(--color-text-primary);
  cursor: pointer;
}
.restore-btn:hover:not(:disabled) {
  background: var(--color-background-secondary);
}
.restore-btn:disabled {
  opacity: 0.45;
  cursor: default;
}
.preview-iframe {
  flex: 1;
  width: 100%;
  border: none;
  background: var(--color-background-secondary);
}
</style>