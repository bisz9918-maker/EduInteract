import { Router } from 'express'
import { spawn } from 'child_process'
import { randomUUID } from 'crypto'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'
import { createInterface } from 'readline'
import { existsSync, readFileSync } from 'fs'
import { requireAuth } from '../middleware/auth.js'

const __filename = fileURLToPath(import.meta.url)
const __dirname = dirname(__filename)
const PYTHON = process.env.PYTHON || resolve(__dirname, '..', '..', '..', '..', '.venv', 'bin', 'python')

const MAX_CONCURRENT = parseInt(process.env.MAX_CONCURRENT_JOBS || '20', 10)
const JOB_TTL_MS = 30 * 60 * 1000  // 30 minutes

interface Job {
  status: 'queued' | 'running' | 'done' | 'error'
  queuePosition: number   // 0 = not queued
  events: string[]
  listeners: Set<(event: string) => void>
  result: { scenes: any[]; texts: string[] } | null
  cmd: string             // serialized command to pass to worker
}

const jobs = new Map<string, Job>()
const queue: string[] = []   // jobIds waiting to run
let running = 0

// topic → jobId mapping to prevent duplicate workers for same topic
const activeTopics = new Map<string, string>()

function scheduleCleanup(jobId: string) {
  setTimeout(() => jobs.delete(jobId), JOB_TTL_MS)
}

function updateQueuePositions() {
  queue.forEach((jid, i) => {
    const j = jobs.get(jid)
    if (j) j.queuePosition = i + 1
  })
}

function notifyQueuePositions() {
  queue.forEach((jid, i) => {
    const j = jobs.get(jid)
    if (!j) return
    const evt = JSON.stringify({ type: 'progress', message: `排队中，第 ${i + 1} 位`, percent: 0, queued: true })
    j.events.push(evt)
    for (const cb of j.listeners) cb(evt)
  })
}

function spawnWorker(ROOT: string, workerPath: string, jobId: string) {
  const job = jobs.get(jobId)
  if (!job) return

  job.status = 'running'
  job.queuePosition = 0
  running++

  // Parse topic from cmd to register in activeTopics
  try {
    const parsed = JSON.parse(job.cmd)
    if (parsed.topic) activeTopics.set(parsed.topic, jobId)
  } catch { /* ignore */ }

  const py = spawn(PYTHON, [workerPath], {
    cwd: ROOT,
    env: { ...process.env },
    stdio: ['pipe', 'pipe', 'pipe'],
  })

  py.on('error', (err) => {
    const evt = JSON.stringify({ type: 'error', message: err.message })
    job.events.push(evt)
    for (const cb of job.listeners) cb(evt)
    for (const cb of job.listeners) cb('__END__')
    job.listeners.clear()
    job.status = 'error'
    scheduleCleanup(jobId)
    running--
    const next = queue.shift()
    if (next) {
      updateQueuePositions()
      notifyQueuePositions()
      spawnWorker(ROOT, workerPath, next)
    }
  })

  py.stdin.on('error', () => { /* EPIPE — child exited early */ })
  py.stdin.write(job.cmd + '\n')
  py.stdin.end()

  const rl = createInterface({ input: py.stdout })
  rl.on('line', (line) => {
    try {
      const evt = JSON.parse(line)
      const eventStr = JSON.stringify(evt)
      job.events.push(eventStr)

      if (evt.type === 'done') {
        job.status = 'done'
        job.result = { scenes: evt.scenes || [], texts: evt.texts || [] }
      } else if (evt.type === 'error') {
        job.status = 'error'
      }

      for (const cb of job.listeners) cb(eventStr)
    } catch { /* ignore non-JSON */ }
  })

  py.stderr.on('data', (data) => process.stderr.write(data))

  py.on('close', () => {
    if (job.status === 'running') job.status = 'error'
    for (const cb of job.listeners) cb('__END__')
    job.listeners.clear()
    scheduleCleanup(jobId)

    // Remove from activeTopics
    try {
      const parsed = JSON.parse(job.cmd)
      if (parsed.topic && activeTopics.get(parsed.topic) === jobId) {
        activeTopics.delete(parsed.topic)
      }
    } catch { /* ignore */ }

    // Dequeue next
    running--
    const next = queue.shift()
    if (next) {
      updateQueuePositions()
      notifyQueuePositions()
      spawnWorker(ROOT, workerPath, next)
    }
  })
}

function enqueue(ROOT: string, workerPath: string, jobId: string) {
  if (running < MAX_CONCURRENT) {
    spawnWorker(ROOT, workerPath, jobId)
  } else {
    queue.push(jobId)
    updateQueuePositions()
    const job = jobs.get(jobId)!
    const evt = JSON.stringify({ type: 'progress', message: `排队中，第 ${job.queuePosition} 位`, percent: 0, queued: true })
    job.events.push(evt)
  }
}

export function generateRouter(ROOT: string, TEACHER_APP: string): Router {
  const router = Router()
  const workerPath = resolve(ROOT, 'teacher_app', 'src', 'bridge', 'worker.py')

  // 解析 TEACHER_MODEL 格式：{{model1:label1},{model2:label2}} 或 model1,model2
  const modelsRaw = process.env.TEACHER_MODEL || 'qwen3.5-397b'
  let modelList: { value: string; label: string }[] = []
  const braceMatch = modelsRaw.match(/\{([^{}]+)\}/g)
  if (braceMatch) {
    for (const item of braceMatch) {
      const inner = item.slice(1, -1)
      const colon = inner.indexOf(':')
      if (colon > 0) {
        modelList.push({ value: inner.slice(0, colon).trim(), label: inner.slice(colon + 1).trim() })
      } else {
        modelList.push({ value: inner.trim(), label: inner.trim() })
      }
    }
  } else {
    modelList = modelsRaw.split(',').map(s => s.trim()).filter(Boolean).map(s => ({ value: s, label: s }))
  }
  const defaultModel = process.env.TEACHER_MODEL_DEFAULT || modelList[0]?.value || 'qwen3.5-397b'

  router.get('/config', (_req, res) => {
    res.json({ model: defaultModel, models: modelList })
  })

  router.post('/generate', (req, res) => {
    const { description, topic, image, model: reqModel } = req.body
    const model = reqModel || defaultModel
    if (!description?.trim()) {
      res.status(400).json({ error: 'description 不能为空' })
      return
    }

    const usedTopic = topic || `teacher_${Date.now()}`

    // If a worker for this topic is already running/queued, reuse its job_id
    const existingJobId = activeTopics.get(usedTopic)
    if (existingJobId && jobs.has(existingJobId)) {
      const existingJob = jobs.get(existingJobId)!
      if (existingJob.status === 'running' || existingJob.status === 'queued') {
        res.json({ job_id: existingJobId, reused: true })
        return
      }
    }

    const jobId = randomUUID()
    const cmd = JSON.stringify({
      action: 'generate',
      description,
      topic: usedTopic,
      model,
      image: image || null,
    })

    const job: Job = {
      status: 'queued',
      queuePosition: 0,
      events: [],
      listeners: new Set(),
      result: null,
      cmd,
    }
    jobs.set(jobId, job)
    activeTopics.set(usedTopic, jobId)
    enqueue(ROOT, workerPath, jobId)

    res.json({ job_id: jobId })
  })

  router.get('/stream/:jobId', (req, res) => {
    const job = jobs.get(req.params.jobId)
    if (!job) { res.status(404).json({ error: 'not found' }); return }

    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
    })

    for (const evt of job.events) res.write(`data: ${evt}\n\n`)

    if (job.status !== 'running' && job.status !== 'queued') { res.end(); return }

    const listener = (event: string) => {
      if (event === '__END__') { res.end(); return }
      res.write(`data: ${event}\n\n`)
    }
    job.listeners.add(listener)
    req.on('close', () => job.listeners.delete(listener))
  })

  router.get('/poll/:jobId', (req, res) => {
    const job = jobs.get(req.params.jobId)
    if (!job) { res.status(404).json({ error: 'not found' }); return }
    const cursor = parseInt(req.query.cursor as string || '0', 10)
    const events = job.events.slice(cursor).map(e => JSON.parse(e))
    res.json({ status: job.status, events, queuePosition: job.queuePosition })
  })

  router.get('/job/:jobId', (req, res) => {
    const job = jobs.get(req.params.jobId)
    if (!job) { res.status(404).json({ error: 'not found' }); return }
    res.json({ status: job.status, result: job.result })
  })

  router.post('/modify_scene', requireAuth, (req, res) => {
    const { topic, scene_number, user_request, use_oah, model: reqModel } = req.body
    const model = reqModel || defaultModel
    if (!topic || !scene_number || !user_request) {
      res.status(400).json({ error: 'topic, scene_number, user_request 不能为空' })
      return
    }

    // 从用户题库读取题目文本和图片
    let problemText: string | null = null
    let problemImage: string | null = null
    try {
      const username = req.user!.username
      const dbPath = resolve(TEACHER_APP, 'data', 'users', username, 'database.json')
      if (existsSync(dbPath)) {
        const db: any[] = JSON.parse(readFileSync(dbPath, 'utf-8'))
        const entry = db.find(e => e.topic === topic)
        if (entry) {
          problemText = entry.problemText || null
          problemImage = entry.problemImage || null
        }
      }
    } catch { /* 读取失败不影响修改流程 */ }

    const jobId = randomUUID()
    const cmd = JSON.stringify({
      action: 'modify_scene',
      topic,
      scene_number,
      user_request,
      use_oah: use_oah !== false,
      model,
      problem_text: problemText,
      problem_image: problemImage,
    })

    const job: Job = {
      status: 'queued',
      queuePosition: 0,
      events: [],
      listeners: new Set(),
      result: null,
      cmd,
    }
    jobs.set(jobId, job)
    enqueue(ROOT, workerPath, jobId)

    res.json({ job_id: jobId })
  })

  return router
}
