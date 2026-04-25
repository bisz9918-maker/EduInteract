import { Router } from 'express'
import { randomUUID } from 'crypto'
import { resolve } from 'path'
import { existsSync, mkdirSync, readFileSync, writeFileSync, renameSync, readdirSync } from 'fs'
import { requireAuth } from '../middleware/auth.js'

interface QuestionRecord {
  id: string
  timestamp: number
  problemText: string
  problemImage?: string
  topic: string
  sceneHistories?: SceneHistory[]
}

interface SceneHistory {
  sceneNum: number
  snapshots: SceneSnapshot[]
  currentIdx: number
}

interface SceneSnapshot {
  url: string
  request: string
  timestamp: string  
}

function getDbPath(appRoot: string, username: string): string {
  const userDir = resolve(appRoot, 'data', 'users', username)
  if (!existsSync(userDir)) mkdirSync(userDir, { recursive: true })
  return resolve(userDir, 'database.json')
}

function readDb(dbPath: string): QuestionRecord[] {
  if (!existsSync(dbPath)) return []
  const raw = readFileSync(dbPath, 'utf-8')
  return JSON.parse(raw)
}

function writeDb(dbPath: string, records: QuestionRecord[]) {
  const tmp = dbPath + '.tmp'
  writeFileSync(tmp, JSON.stringify(records, null, 2), 'utf-8')
  renameSync(tmp, dbPath)
}

// Per-user db lock map
const dbLocks = new Map<string, Promise<void>>()
function withDbLock<T>(username: string, fn: () => T): Promise<T> {
  const current = dbLocks.get(username) ?? Promise.resolve()
  const result = current.then(fn)
  dbLocks.set(username, result.then(() => {}, () => {}))
  return result
}

function scanScenes(root: string, topic: string): { num: number; url: string }[] {
  const filePrefix = topic.toLowerCase().replace(/[^a-z0-9_]+/g, '_')
  const topicDir = resolve(root, 'output', 'teacher', filePrefix)
  if (!existsSync(topicDir)) return []

  const scenes: { num: number; url: string }[] = []
  try {
    for (const entry of readdirSync(topicDir)) {
      const m = entry.match(/^scene(\d+)$/)
      if (!m) continue
      const sceneNum = parseInt(m[1], 10)
      const codeDir = resolve(topicDir, entry, 'code')
      if (!existsSync(codeDir)) continue
      const htmlFiles = readdirSync(codeDir)
        .filter(f => f.endsWith('.html') && f.includes(`scene${sceneNum}`))
        .sort()
      if (htmlFiles.length > 0) {
        const latest = htmlFiles[htmlFiles.length - 1]
        scenes.push({ num: sceneNum, url: `doc/output/teacher/${filePrefix}/scene${sceneNum}/code/${latest}` })
      }
    }
  } catch { /* ignore */ }
  scenes.sort((a, b) => a.num - b.num)
  return scenes
}

function parseTexts(root: string, topic: string): string[] {
  const filePrefix = topic.toLowerCase().replace(/[^a-z0-9_]+/g, '_')
  const outlinePath = resolve(root, 'output', 'teacher', filePrefix, `${filePrefix}_scene_outline.txt`)
  if (!existsSync(outlinePath)) return []
  try {
    const content = readFileSync(outlinePath, 'utf-8')
    const texts: string[] = []
    const re = /<TEXT_\d+>([\s\S]*?)<\/TEXT_\d+>/gi
    let match
    while ((match = re.exec(content)) !== null) texts.push(match[1].trim())
    return texts
  } catch { return [] }
}

export function bankRouter(ROOT: string, APP_ROOT: string): Router {
  const router = Router()

  // All bank routes require auth
  router.use(requireAuth)

  router.post('/bank/save', async (req, res) => {
  const { problemText, problemImage, topic, sceneHistories } = req.body  
  const username = req.user!.username
  if (!problemText?.trim() || !topic?.trim()) {
    res.status(400).json({ error: 'problemText and topic are required' })
    return
  }
  try {
    await withDbLock(username, () => {
      const dbPath = getDbPath(APP_ROOT, username)
      let records: QuestionRecord[]
      try { records = readDb(dbPath) } catch { records = [] }
      const existing = records.find(r => r.topic === topic)
      if (existing) {
        existing.problemText = problemText
        if (problemImage) existing.problemImage = problemImage
        if (sceneHistories) existing.sceneHistories = sceneHistories  
        existing.timestamp = Date.now()
      } else {
        const record: QuestionRecord = { 
          id: randomUUID(), 
          timestamp: Date.now(), 
          problemText, 
          topic,
          sceneHistories  
        }
        if (problemImage) record.problemImage = problemImage
        records.push(record)
      }
      writeDb(dbPath, records)
      return existing ? { id: existing.id, updated: true } : { id: records[records.length - 1].id }
    }).then(result => res.json(result))
  } catch (e: any) {
    res.status(500).json({ error: '写入失败: ' + e.message })
  }
})

  router.get('/bank/list', (req, res) => {
    const username = req.user!.username
    const dbPath = getDbPath(APP_ROOT, username)
    let records: QuestionRecord[]
    try { records = readDb(dbPath) } catch { records = [] }
    const list = records.map(r => {
      const scenes = scanScenes(ROOT, r.topic)
      const filePrefix = r.topic.toLowerCase().replace(/[^a-z0-9_]+/g, '_')
      const solutionPath = resolve(ROOT, 'output', 'teacher', filePrefix, 'doc', 'solution.html')
      return {
        id: r.id,
        timestamp: r.timestamp,
        problemText: r.problemText,
        topic: r.topic,
        sceneCount: scenes.length,
        completed: existsSync(solutionPath),
      }
    })
    list.sort((a, b) => b.timestamp - a.timestamp)
    res.json(list)
  })

  router.delete('/bank/:id', async (req, res) => {
    const username = req.user!.username
    try {
      await withDbLock(username, () => {
        const dbPath = getDbPath(APP_ROOT, username)
        const records = readDb(dbPath)
        const idx = records.findIndex(r => r.id === req.params.id)
        if (idx === -1) throw Object.assign(new Error('not found'), { status: 404 })
        records.splice(idx, 1)
        writeDb(dbPath, records)
      })
      res.json({ ok: true })
    } catch (e: any) {
      res.status(e.status || 500).json({ error: e.message })
    }
  })

  router.get('/bank/:id', (req, res) => {
    const username = req.user!.username
    const dbPath = getDbPath(APP_ROOT, username)
    let records: QuestionRecord[]
    try { records = readDb(dbPath) } catch { records = [] }
    const record = records.find(r => r.id === req.params.id)
    if (!record) { res.status(404).json({ error: 'not found' }); return }
    const scenes = scanScenes(ROOT, record.topic)
    const texts = parseTexts(ROOT, record.topic)
    res.json({ 
      ...record, 
      scenes, 
      texts,
      sceneHistories: record.sceneHistories || []  
    })
  })

  return router
}
