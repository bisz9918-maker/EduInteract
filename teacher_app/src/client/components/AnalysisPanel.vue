<template>
  <div class="guide-problem-analysis" @copy.capture="onCopy">
    <div class="guide-panel-header">
      <span class="guide-problem-label">解析</span>
    </div>
    <div v-if="texts.length === 0" style="color:var(--text-sub);font-size:.82rem;">等待生成…</div>
    <div v-for="(text, i) in texts" :key="i" style="margin-bottom:12px;">
      <div style="display:flex;align-items:center;gap:6px;margin-bottom:4px;">
        <span style="font-size:.78rem;font-weight:600;color:var(--primary);">解析 {{ i + 1 }}</span>
        <button class="tts-btn" :class="{ playing: playingIndex === i }" @click="play(text, i)">🔊</button>
      </div>
      <div class="guide-analysis-body" v-html="renderMarkdown(text)" ref="contentRefs"></div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ref } from 'vue'
import { useTTS } from '../composables/useTTS'

declare const marked: { parse: (s: string) => string }

const props = defineProps<{ texts: string[] }>()
const { playingIndex, play } = useTTS()
const contentRefs = ref<HTMLElement[]>([])

function renderMarkdown(text: string): string {
  // 去掉公共缩进，防止 marked 把缩进文本识别为代码块
  const lines = text.split('\n')
  const indents = lines
    .filter(l => l.trim())
    .map(l => l.match(/^(\s*)/)?.[1].length ?? 0)
    .filter(n => n > 0)
  const indent = indents.length > 0 ? Math.min(...indents) : 0
  // 只对有缩进的行去缩进，避免切掉第一行（trim后无缩进）的内容
  const dedented = indent > 0
    ? lines.map(l => l.startsWith(' '.repeat(indent)) ? l.slice(indent) : l).join('\n')
    : text
  return marked.parse(dedented)
}

// 复制时把 MathJax 渲染节点替换回原始 $...$ 文本
function onCopy(e: ClipboardEvent) {
  const sel = window.getSelection()
  if (!sel || sel.isCollapsed) return
  const fragment = sel.getRangeAt(0).cloneContents()
  fragment.querySelectorAll('mjx-container').forEach(el => {
    const tex = el.getAttribute('data-tex') || ''
    const isDisplay = el.getAttribute('data-display') === 'true'
    el.replaceWith(document.createTextNode(isDisplay ? `$$${tex}$$` : `$${tex}$`))
  })
  const div = document.createElement('div')
  div.appendChild(fragment)
  const plain = div.innerText || div.textContent || ''
  if (plain) {
    e.preventDefault()
    e.clipboardData?.setData('text/plain', plain)
  }
}
</script>

