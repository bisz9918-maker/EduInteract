import express from 'express'
import cors from 'cors'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'
import { existsSync, mkdirSync, renameSync } from 'fs'
import { config } from 'dotenv'
import { generateRouter } from './routes/generate.js'
import { proxyRouter } from './routes/proxy.js'
import { chatRouter } from './routes/chat.js'
import { docRouter } from './routes/doc.js'
import { bankRouter } from './routes/bank.js'
import { authRouter } from './routes/auth.js'

const __dirname = dirname(fileURLToPath(import.meta.url))
const ROOT = resolve(__dirname, '..', '..', '..')  // TheoremExplainAgent root
const TEACHER_APP = resolve(ROOT, 'teacher_app')   // always teacher_app/, regardless of tsx vs dist

// 加载项目根目录的 .env
config({ path: resolve(ROOT, '.env'), override: true })

// Migrate legacy database.json → data/users/test/database.json
function migrateLegacyDb() {
  const legacy = resolve(TEACHER_APP, 'data', 'database.json')
  if (!existsSync(legacy)) return
  const testDir = resolve(TEACHER_APP, 'data', 'users', 'test')
  if (!existsSync(testDir)) mkdirSync(testDir, { recursive: true })
  const target = resolve(testDir, 'database.json')
  if (!existsSync(target)) {
    renameSync(legacy, target)
    console.log('Migrated legacy database.json → data/users/test/database.json')
  }
}
migrateLegacyDb()

const PORT = parseInt(process.env.SERVER_PORT || process.env.PORT || '8765', 10)

const app = express()
app.use(cors())
app.use(express.json({ limit: '50mb' }))
app.use(express.raw({ type: 'application/octet-stream', limit: '10mb' }))

// Request logging
app.use((req, _res, next) => {
  console.log(`[${new Date().toISOString()}] ${req.method} ${req.url}`)
  next()
})

// API routes
app.use('/api', authRouter(TEACHER_APP))
app.use('/api', generateRouter(ROOT, TEACHER_APP))
app.use('/api', proxyRouter())
app.use('/api', chatRouter())
app.use('/api', bankRouter(ROOT, TEACHER_APP))
app.use('/doc', docRouter(ROOT))

// Serve frontend (production build)
const distClient = resolve(TEACHER_APP, 'dist', 'client')
if (existsSync(distClient)) {
  // assets have hash in filename → long cache; index.html → no cache
  app.use('/assets', express.static(resolve(distClient, 'assets'), {
    maxAge: '30d', immutable: true,
  }))
  app.use(express.static(distClient, {
    setHeaders: (res, filePath) => {
      if (filePath.endsWith('.html')) {
        res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate')
      }
    },
  }))
  app.get('/*path', (_req, res) => {
    res.setHeader('Cache-Control', 'no-cache, no-store, must-revalidate')
    res.sendFile(resolve(distClient, 'index.html'))
  })
}

app.listen(PORT, '0.0.0.0', () => {
  console.log(`教师备课助手启动于 http://0.0.0.0:${PORT}`)
})
