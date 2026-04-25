<template>
  <!-- Login page -->
  <LoginPage v-if="!loggedIn" @success="onLoginSuccess" />

  <!-- Main app -->
  <template v-else>
    <!-- Header -->
    <header class="app-header">
      <img :src="publicUrl('header-logo.webp')" class="logo-img" alt="Logo">
      <div class="divider"></div>
      <span class="app-name">教师备课助手</span>
      <div class="header-actions">
        <button class="btn btn-secondary btn-sm" @click="showBank = true">查看题库</button>
        <button
          v-if="hasContent"
          class="btn btn-secondary btn-sm history-btn"
          @click="showHistory = true"
        >
          修改历史
          <span v-if="totalSnapshots > 0" class="history-badge">{{ totalSnapshots }}</span>
        </button>
        <button
          v-if="hasContent"
          class="btn btn-primary btn-sm"
          @click="onSaveToBank"
        >保存题库</button>
        <div class="model-switcher" v-if="modelList.length > 1">
          <button
            v-for="m in modelList"
            :key="m.value"
            class="model-option"
            :class="{ active: selectedModel === m.value }"
            @click="selectedModel = m.value"
          >{{ m.label }}</button>
        </div>
      </div>
      <div class="status-area">
        {{ status }}
        <div class="progress-bar" v-show="generating">
          <div class="progress-fill" :style="{ width: progress + '%' }"></div>
        </div>
      </div>
      <div class="header-user">
        <span class="user-name">{{ currentUser }}</span>
        <button class="btn btn-secondary btn-sm" @click="onLogout">退出</button>
      </div>
    </header>

    <!-- Topbar: 题目输入 -->
    <ProblemInput
      v-model="problemText"
      :disabled="generating"
      :canContinue="canContinue"
      :setStatus="setStatus"
      @generate="onGenerate"
      @continue="onContinue"
      @update:image="onImageUpdate"
    />

    <!-- Guide Body -->
    <div class="guide-body">
      <!-- 上半：题目+图示 -->
      <div class="guide-top" v-show="hasContent">
        <!-- 左：解析 -->
        <div class="guide-problem">
          <div class="guide-problem-top">
            <div class="guide-panel-header">
              <span class="guide-problem-label">题目</span>
            </div>
            <div class="guide-problem-text" ref="problemEl" v-html="renderedProblem"></div>
            <img v-if="problemImage" :src="'data:image/png;base64,' + problemImage" class="problem-image" alt="题目图片">
          </div>
          <AnalysisPanel :texts="texts" />
        </div>

        <!-- 右：图示 -->
        <SceneViewer
          :scenes="scenes"
          :activeScene="activeScene"
          :generating="generating"
          @select="selectScene"
        />
      </div>

      <!-- Empty state -->
      <div v-if="!hasContent" class="guide-scene-empty" style="margin:auto;">
        请输入题目并点击"生成图示"
      </div>

      <!-- Input Bar (floating, bottom right) -->
      <BottomBar
        v-show="hasContent"
        :generating="generating"
        :activeScene="activeScene"
        @modifyScene="onModifyScene"
      />
    </div>

    <!-- Question Bank Modal -->
    <QuestionBank
      :open="showBank"
      @close="showBank = false"
      @restore="onRestoreQuestion"
      @continue="onContinueQuestion"
    />

    <!-- History Drawer -->
    <HistoryDrawer
      :open="showHistory"
      :sceneHistories="sceneHistories"
      @close="showHistory = false"
      @restore="onRestoreSnapshot"
    />
  </template>
</template>

<script setup lang="ts">
import { ref, computed, watch, nextTick, onMounted } from 'vue'
import ProblemInput from './components/ProblemInput.vue'
import AnalysisPanel from './components/AnalysisPanel.vue'
import SceneViewer from './components/SceneViewer.vue'
import BottomBar from './components/BottomBar.vue'
import QuestionBank from './components/QuestionBank.vue'
import LoginPage from './components/LoginPage.vue'
import HistoryDrawer from './components/HistoryDrawer.vue'
import { useGenerate } from './composables/useGenerate'
import { currentUser, initAuth, logout } from './composables/useAuth'
import { apiFetch, selectedModel, modelList, fetchConfig } from './utils/api'

declare const marked: { parse: (s: string) => string }
declare const MathJax: { typesetPromise?: (el: Element[]) => Promise<void>; startup?: { promise: Promise<void> } }

const BASE = import.meta.env.BASE_URL
function publicUrl(name: string) { return `${BASE}${name}` }

const loggedIn = ref(false)
const problemText = ref('')
const problemImage = ref('')
const problemEl = ref<HTMLElement | null>(null)
const showBank = ref(false)
const showHistory = ref(false)
const canContinue = ref(false)
const restoredData = ref<any>(null)

const {
  status, scenes, texts, activeScene, generating, progress, currentTopic,
  sceneHistories,
  startGenerate, continueGenerate, selectScene, modifyScene, updateScene,
  restoreHistories,
} = useGenerate()

const hasContent = computed(() => scenes.value.length > 0 || texts.value.length > 0 || generating.value)
const renderedProblem = computed(() => problemText.value ? marked.parse(problemText.value) : '')

// total number of snapshots across all scenes (excluding the initial "初始生成" ones)
// used for the badge count — shows how many modifications have been made
const totalSnapshots = computed(() =>
  sceneHistories.value.reduce((sum, h) => sum + Math.max(0, h.snapshots.length - 1), 0)
)

onMounted(async () => {
  loggedIn.value = await initAuth()
  await fetchConfig()
})

function onLoginSuccess() {
  loggedIn.value = true
}

function onLogout() {
  logout()
  loggedIn.value = false
}

watch(renderedProblem, async () => {
  await nextTick()
  if (problemEl.value && typeof MathJax !== 'undefined' && MathJax.typesetPromise) {
    MathJax.typesetPromise([problemEl.value])
  }
})

async function typesetAnalysis() {
  await nextTick()
  await nextTick()
  for (let i = 0; i < 100; i++) {
    if (typeof MathJax !== 'undefined' && MathJax.typesetPromise) break
    await new Promise(r => setTimeout(r, 100))
  }
  if (typeof MathJax === 'undefined' || !MathJax.typesetPromise) return
  try {
    const els = Array.from(document.querySelectorAll('.guide-analysis-body')) as HTMLElement[]
    if (!els.length) return

    const texMap = new Map<HTMLElement, string[]>()
    const inlineRe = /\$\$[\s\S]*?\$\$|\$[^$\n]+?\$/g
    for (const el of els) {
      const matches = [...el.innerHTML.matchAll(inlineRe)].map(m => m[0])
      texMap.set(el, matches)
    }

    await MathJax.typesetPromise(els)

    for (const el of els) {
      const texList = texMap.get(el) || []
      const containers = el.querySelectorAll('mjx-container')
      containers.forEach((c, i) => {
        if (texList[i]) {
          const raw = texList[i].replace(/^\$\$|\$\$$/g, '').replace(/^\$|\$$/g, '')
          c.setAttribute('data-tex', raw)
          c.setAttribute('data-display', texList[i].startsWith('$$') ? 'true' : 'false')
        }
      })
    }
  } catch { /* ignore */ }
}

watch(() => texts.value, (val) => { if (val.length) typesetAnalysis() }, { deep: true })

function setStatus(msg: string) {
  status.value = msg
}

function onImageUpdate(b64: string) {
  problemImage.value = b64
}

function onGenerate() {
  canContinue.value = false
  startGenerate(problemText.value, undefined, problemImage.value || undefined)
}

function onContinue() {
  if (!restoredData.value) return
  canContinue.value = false
  continueGenerate(restoredData.value.problemText, restoredData.value.topic, restoredData.value.scenes || [], restoredData.value.problemImage || undefined)
}

function onModifyScene(userRequest: string) {
  const sceneNum = activeScene.value > 0 ? activeScene.value : 1
  modifyScene(sceneNum, userRequest)
}

// Restore a specific snapshot from the history drawer
function onRestoreSnapshot(sceneNum: number, url: string) {
  updateScene(sceneNum, url, '恢复旧版本')
  showHistory.value = false
}

async function onSaveToBank() {
  if (!currentTopic.value || !problemText.value.trim()) return
  status.value = '正在保存到题库…'
  try {
    const resp = await apiFetch('api/bank/save', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        problemText: problemText.value,
        problemImage: problemImage.value || undefined,
        topic: currentTopic.value,
        sceneHistories: sceneHistories.value,  
      }),
    })
    const data = await resp.json()
    if (!resp.ok) {
      status.value = '保存失败: ' + (data.error || resp.status)
      return
    }
    status.value = data.updated ? '题库已更新' : '已保存到题库'
  } catch {
    status.value = '保存失败'
  }
}

function onContinueQuestion(data: any) {
  onRestoreQuestion(data)
  restoredData.value = data
  canContinue.value = true
  showBank.value = false
}

function onRestoreQuestion(data: any) {
  scenes.value = []
  texts.value = []
  activeScene.value = -1
  
  const newTopic = data.topic || ''
  currentTopic.value = newTopic

  let histories = data.sceneHistories || []

  if (histories.length === 0 && data.scenes?.length > 0) {
    histories = data.scenes.map((s: any) => ({
      sceneNum: s.num,
      currentIdx: 0,
      snapshots: [
        {
          url: s.url,
          request: '初始状态',
          timestamp: new Date().toISOString()
        }
      ]
    }))
  }

  restoreHistories(newTopic, histories)

  problemText.value = data.problemText || ''
  problemImage.value = data.problemImage || ''
  
  if (data.scenes?.length) {
    scenes.value = [...data.scenes].sort((a, b) => a.num - b.num)
    activeScene.value = scenes.value[0].num
  }
  
  texts.value = data.texts || []
  
  typesetAnalysis()
}
</script>

<style scoped>
/* History button badge */
.history-btn {
  position: relative;
}
.history-badge {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  min-width: 16px;
  height: 16px;
  padding: 0 4px;
  border-radius: 8px;
  background: var(--color-background-danger);
  color: var(--color-text-danger);
  font-size: 10px;
  font-weight: 500;
  margin-left: 4px;
  line-height: 1;
}
</style>