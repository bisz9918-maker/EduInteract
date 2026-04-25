import { ref, type Ref, computed } from 'vue'
import { apiFetch, selectedModel } from '../utils/api'

export interface Scene {
  num: number
  url: string
  name?: string
}

export interface SceneSnapshot {
  url: string
  request: string
  timestamp: Date
}

export interface SceneHistory {
  sceneNum: number
  snapshots: SceneSnapshot[]
  currentIdx: number
}

export interface GenerateState {
  status: Ref<string>
  scenes: Ref<Scene[]>
  texts: Ref<string[]>
  activeScene: Ref<number>
  generating: Ref<boolean>
  progress: Ref<number>
  currentTopic: Ref<string>
  sceneHistories: Ref<SceneHistory[]>
  startGenerate: (description: string, topic?: string, image?: string) => void
  continueGenerate: (description: string, topic: string, existingScenes: Scene[], image?: string) => void
  selectScene: (num: number) => void
  modifyScene: (sceneNum: number, userRequest: string, useOah?: boolean) => void
  updateScene: (num: number, url: string, request?: string) => void
  restoreHistories: (topic: string, histories: SceneHistory[]) => void
}

// ─── localStorage 持久化 ───────────────────────────────────────────

const STORAGE_KEY = 'scene_histories_v1'
const MAX_TOPICS = 20

function saveToStorage(map: Map<string, SceneHistory[]>) {
  try {
    const entries = Array.from(map.entries())
    // 只保留最近 MAX_TOPICS 道题，防止超出 5MB 限制
    const trimmed = entries.slice(-MAX_TOPICS)
    const serializable = trimmed.map(([topic, histories]) => [
      topic,
      histories.map(h => ({
        ...h,
        snapshots: h.snapshots.map(s => ({
          ...s,
          timestamp: s.timestamp instanceof Date
            ? s.timestamp.toISOString()
            : s.timestamp,
        })),
      })),
    ])
    localStorage.setItem(STORAGE_KEY, JSON.stringify(serializable))
  } catch {
    // ignore quota errors
  }
}

function loadFromStorage(): Map<string, SceneHistory[]> {
  try {
    const raw = localStorage.getItem(STORAGE_KEY)
    if (!raw) return new Map()
    const entries = JSON.parse(raw) as [string, any[]][]
    const map = new Map<string, SceneHistory[]>()
    for (const [topic, histories] of entries) {
      map.set(topic, histories.map(h => ({
        ...h,
        snapshots: h.snapshots.map((s: any) => ({
          ...s,
          timestamp: new Date(s.timestamp),  // string → Date
        })),
      })))
    }
    return map
  } catch {
    return new Map()
  }
}

// ─── composable ───────────────────────────────────────────────────

export function useGenerate(): GenerateState {
  const status = ref('就绪')
  const scenes = ref<Scene[]>([])
  const texts = ref<string[]>([])
  const activeScene = ref(-1)
  const generating = ref(false)
  const progress = ref(0)
  const currentTopic = ref('')

  // 初始化时从 localStorage 恢复所有历史
  const allHistories = ref<Map<string, SceneHistory[]>>(loadFromStorage())

  // 当前题目的历史，随 currentTopic 自动切换
  const sceneHistories = computed<SceneHistory[]>(() => {
    if (!currentTopic.value) return []
    return allHistories.value.get(currentTopic.value) || []
  })

  // ─── history helpers ──────────────────────────────────────────

  function pushSnapshot(sceneNum: number, rawUrl: string, request: string) {
    const cleanUrl = rawUrl.split('?')[0]

    let histories = allHistories.value.get(currentTopic.value)
    if (!histories) {
      // 替换整个 Map 实例以触发 Vue 响应式更新
      const next = new Map(allHistories.value)
      histories = []
      next.set(currentTopic.value, histories)
      allHistories.value = next
    }

    let history = histories.find(h => h.sceneNum === sceneNum)
    if (!history) {
      history = { sceneNum, snapshots: [], currentIdx: 0 }
      histories.push(history)
      histories.sort((a, b) => a.sceneNum - b.sceneNum)
    }

    // 去重：url 和 request 完全相同时跳过
    const lastSnap = history.snapshots[history.snapshots.length - 1]
    if (lastSnap && lastSnap.url === cleanUrl && lastSnap.request === request) {
      return
    }

    history.snapshots.push({ url: cleanUrl, request, timestamp: new Date() })
    history.currentIdx = history.snapshots.length - 1

    saveToStorage(allHistories.value)
  }

  // ─── scene helpers ────────────────────────────────────────────

  function addScene(num: number, url: string) {
    if (scenes.value.find(s => s.num === num)) return
    scenes.value.push({ num, url })
    scenes.value.sort((a, b) => a.num - b.num)
    if (activeScene.value < 0) activeScene.value = num
    pushSnapshot(num, url, '初始生成')
  }

  function selectScene(num: number) {
    activeScene.value = num
  }

  // ─── generate ─────────────────────────────────────────────────

  function startGenerate(description: string, topic?: string, image?: string) {
    if (!description.trim() || generating.value) return

    const usedTopic = topic || `teacher_${Date.now()}`
    currentTopic.value = usedTopic
    generating.value = true
    scenes.value = []
    texts.value = []
    activeScene.value = -1
    progress.value = 0
    status.value = '正在提交任务…'

    const payload: any = { description, topic: usedTopic }
    if (image) payload.image = image
    if (selectedModel.value) payload.model = selectedModel.value

    apiFetch('api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then(r => {
        status.value = '已连接，等待响应…'
        return r.json()
      })
      .then(data => {
        if (data.error) {
          status.value = '错误: ' + data.error
          generating.value = false
          return
        }
        status.value = '任务已提交，正在生成…'
        listenSSE(data.job_id)
      })
      .catch((e) => {
        status.value = '请求失败: ' + e.message
        generating.value = false
      })
  }

  function continueGenerate(description: string, topic: string, existingScenes: Scene[], image?: string) {
    if (!description.trim() || generating.value) return

    currentTopic.value = topic
    generating.value = true
    scenes.value = [...existingScenes]
    if (scenes.value.length > 0) activeScene.value = scenes.value[0].num
    progress.value = 0
    status.value = '正在继续生成…'

    const payload: any = { description, topic }
    if (image) payload.image = image
    if (selectedModel.value) payload.model = selectedModel.value

    apiFetch('api/generate', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          status.value = '错误: ' + data.error
          generating.value = false
          return
        }
        listenSSE(data.job_id)
      })
      .catch((e) => {
        status.value = '请求失败: ' + e.message
        generating.value = false
      })
  }

  // ─── update / modify ──────────────────────────────────────────

  function updateScene(num: number, url: string, request = '') {
    const existing = scenes.value.find(s => s.num === num)
    const isRestore = request === '恢复旧版本'
    const finalUrl = isRestore ? url : (url + '?t=' + Date.now())

    if (existing) {
      existing.url = finalUrl
    } else {
      scenes.value.push({ num, url: finalUrl })
      scenes.value.sort((a, b) => a.num - b.num)
    }
    activeScene.value = num

    // --- 关键修复：同步 currentIdx ---
    const histories = allHistories.value.get(currentTopic.value)
    const history = histories?.find(h => h.sceneNum === num)
    
    if (history) {
      if (isRestore) {
        // 恢复模式：根据 URL 找到对应的索引并锁定
        const cleanUrl = url.split('?')[0]
        const idx = history.snapshots.findIndex(s => s.url === cleanUrl)
        if (idx !== -1) {
          history.currentIdx = idx // 锁定到 v1
        }
      } else {
        // 修改模式：新增快照并指向最后一位
        pushSnapshot(num, url, request) 
      }
      // 每次更新后强制保存到存储
      saveToStorage(allHistories.value)
    }
  }

  // pendingRequest：modifyScene 写入，listenSSE scene_ready 消费
  let pendingRequest = ''

  function modifyScene(sceneNum: number, userRequest: string, useOah = true) {
    if (generating.value) {
      status.value = '请等待生成完成后再修改'
      return
    }
    if (!currentTopic.value) return

    pendingRequest = userRequest
    generating.value = true
    status.value = '正在修改图示…'

    apiFetch('api/modify_scene', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        topic: currentTopic.value,
        scene_number: sceneNum,
        user_request: userRequest,
        use_oah: useOah,
        ...(selectedModel.value ? { model: selectedModel.value } : {}),
      }),
    })
      .then(r => r.json())
      .then(data => {
        if (data.error) {
          status.value = '修改失败: ' + data.error
          generating.value = false
          return
        }
        listenSSE(data.job_id, true)
      })
      .catch((e) => {
        status.value = '请求失败: ' + e.message
        generating.value = false
      })
  }

  // ─── SSE polling ──────────────────────────────────────────────

  function listenSSE(jobId: string, isModify = false) {
    let cursor = 0

    const poll = async () => {
      try {
        const resp = await apiFetch(`api/poll/${jobId}?cursor=${cursor}`)
        if (!resp.ok) {
          status.value = isModify ? '修改失败：服务已重启，请重试' : '生成中断：服务已重启，请重新生成'
          generating.value = false
          return
        }
        const data = await resp.json()

        if (data.status === 'queued' && data.queuePosition > 0) {
          status.value = `排队中，第 ${data.queuePosition} 位…`
          setTimeout(poll, 2000)
          return
        }

        for (const evt of data.events) {
          cursor++
          if (evt.type === 'progress') {
            status.value = evt.message
            if (evt.percent != null) progress.value = evt.percent
          } else if (evt.type === 'scene_ready') {
            if (isModify) {
              updateScene(evt.scene, evt.url, pendingRequest)
            } else {
              addScene(evt.scene, evt.url)
            }
          } else if (evt.type === 'done') {
            if (!isModify && evt.scenes?.length) {
              scenes.value = []
              evt.scenes.forEach((s: any, i: number) => addScene(i + 1, s.url))
            }
            if (!isModify && evt.texts) texts.value = evt.texts
            status.value = isModify ? '修改完成' : '生成完成'
            progress.value = 100
            generating.value = false
            pendingRequest = ''
            return
          } else if (evt.type === 'error') {
            status.value = '错误: ' + evt.message
            generating.value = false
            pendingRequest = ''
            return
          }
        }

        if (data.status === 'running' || data.status === 'queued') {
          setTimeout(poll, 1500)
        } else if (data.status === 'error') {
          if (!status.value.includes('错误') && !status.value.includes('失败')) {
            status.value = isModify ? '修改失败' : '生成失败'
          }
          generating.value = false
        } else if (!data.events.length) {
          // done 状态且无新事件，只有前面已处理过 done 事件才到这里
          if (status.value === '正在继续生成…' || status.value === '正在修改图示…' || status.value === '任务已提交，正在生成…') {
            status.value = isModify ? '修改失败：未收到结果' : '生成失败：未收到结果'
          }
          generating.value = false
        }
      } catch {
        status.value = '连接中断'
        generating.value = false
      }
    }

    poll()
  }

  // ─── restoreHistories（从题库恢复时调用）────────────────────────

  function restoreHistories(topic: string, histories: SceneHistory[]) {
    const next = new Map(allHistories.value)
    next.set(topic, histories)
    allHistories.value = next
    saveToStorage(allHistories.value)
  }

  return {
    status, scenes, texts, activeScene, generating, progress, currentTopic,
    sceneHistories,
    startGenerate, continueGenerate, selectScene, modifyScene, updateScene,
    restoreHistories,
  }
}