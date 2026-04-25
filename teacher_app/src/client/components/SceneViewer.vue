<template>
  <div class="guide-scene">
    <div class="guide-scene-label">步骤图示</div>

    <!-- Scene tabs -->
    <div class="scene-tabs" v-if="scenes.length">
      <div
        v-for="s in scenes"
        :key="s.num"
        class="tab"
        :class="{ active: s.num === activeScene }"
        @click="$emit('select', s.num)"
      >
        Scene {{ s.num }}
      </div>
    </div>

    <!-- iframe -->
    <div v-if="currentUrl" class="scene-iframe-wrap">
      <button class="scene-download-btn" @click="downloadScene" title="下载当前图示">⬇</button>
      <iframe ref="iframeEl" :src="currentUrl" sandbox="allow-scripts allow-same-origin" @load="onIframeLoad"></iframe>
    </div>

    <!-- Empty state -->
    <div v-else class="guide-scene-empty">
      <div>{{ generating ? '正在生成中…' : '等待生成图示' }}</div>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { apiUrl } from '../utils/api'
import type { Scene } from '../composables/useGenerate'

const props = defineProps<{
  scenes: Scene[]
  activeScene: number
  generating: boolean
}>()

defineEmits<{ select: [num: number] }>()

const iframeEl = ref<HTMLIFrameElement | null>(null)

const currentUrl = computed(() => {
  const s = props.scenes.find(x => x.num === props.activeScene)
  return s?.url ? apiUrl(s.url) : ''
})

const currentScene = computed(() => props.scenes.find(x => x.num === props.activeScene))

function onIframeLoad() {
  const doc = iframeEl.value?.contentDocument
  if (!doc) return
  const html = doc.documentElement?.innerHTML || ''
  if (!html.includes('$')) return  // 无 LaTeX

  // Observer 脚本：监听动态 innerHTML 变化后自动 typeset，带防抖避免影响动画性能
  const obsCode = `(function() {
    if (window.__mjObserverInstalled) return;
    window.__mjObserverInstalled = true;
    var timer = null;
    var pending = new Set();
    var observer = new MutationObserver(function(mutations) {
      if (!window.MathJax || !window.MathJax.typesetPromise) return;
      mutations.forEach(function(m) {
        var node = m.type === 'characterData' ? m.target.parentElement : m.target;
        if (node && node.textContent && node.textContent.indexOf('$') >= 0) {
          pending.add(node);
        }
      });
      if (!pending.size) return;
      clearTimeout(timer);
      timer = setTimeout(function() {
        var nodes = Array.from(pending); pending.clear();
        window.MathJax.typesetPromise(nodes).catch(function(){});
      }, 200);
    });
    observer.observe(document.body || document.documentElement,
      { childList: true, subtree: true, characterData: true });
  })();`

  // 已有 MathJax，只补 Observer
  if (/mathjax|katex/i.test(html)) {
    const s = doc.createElement('script')
    s.text = obsCode
    doc.head.appendChild(s)
    return
  }

  // 完整注入 MathJax 配置 + CDN + Observer
  const cfg = doc.createElement('script')
  cfg.text = `window.MathJax = {
    tex: { inlineMath: [['$','$'],['\\\\(','\\\\)']], displayMath: [['$$','$$'],['\\\\[','\\\\]']] },
    options: { skipHtmlTags: ['script','noscript','style','textarea','pre'] }
  };`
  doc.head.appendChild(cfg)

  const mj = doc.createElement('script')
  mj.src = 'https://cdn.jsdelivr.net/npm/mathjax@3/es5/tex-mml-chtml.js'
  mj.defer = true
  doc.head.appendChild(mj)

  const obs = doc.createElement('script')
  obs.text = obsCode
  doc.head.appendChild(obs)
}

async function downloadScene() {
  const url = currentUrl.value
  if (!url) return
  try {
    const resp = await fetch(url)
    const blob = await resp.blob()
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    // derive filename from url path, strip query string/hash
    const rawName = url.split('/').pop() || `scene${props.activeScene}.html`
    const filename = rawName.split('?')[0].split('#')[0]
    a.download = filename
    a.click()
    URL.revokeObjectURL(a.href)
  } catch { /* ignore */ }
}
</script>
