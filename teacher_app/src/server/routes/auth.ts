import { Router } from 'express'
import { randomUUID } from 'crypto'
import { resolve } from 'path'
import { existsSync, mkdirSync, readFileSync, writeFileSync, renameSync } from 'fs'
import bcrypt from 'bcryptjs'
import jwt from 'jsonwebtoken'
import { JWT_SECRET } from '../middleware/auth.js'

interface UserRecord {
  id: string
  username: string
  passwordHash: string
  createdAt: number
}

function getUsersPath(appRoot: string): string {
  const dataDir = resolve(appRoot, 'data')
  if (!existsSync(dataDir)) mkdirSync(dataDir, { recursive: true })
  return resolve(dataDir, 'users.json')
}

function readUsers(usersPath: string): UserRecord[] {
  if (!existsSync(usersPath)) return []
  try { return JSON.parse(readFileSync(usersPath, 'utf-8')) } catch { return [] }
}

function writeUsers(usersPath: string, users: UserRecord[]) {
  const tmp = usersPath + '.tmp'
  writeFileSync(tmp, JSON.stringify(users, null, 2), 'utf-8')
  renameSync(tmp, usersPath)
}

export function authRouter(APP_ROOT: string): Router {
  const router = Router()
  const usersPath = getUsersPath(APP_ROOT)

  router.post('/auth/register', async (req, res) => {
    const { username, password } = req.body
    if (!username?.trim() || !password?.trim()) {
      res.status(400).json({ error: '用户名和密码不能为空' })
      return
    }
    if (!/^[a-zA-Z0-9_]{2,20}$/.test(username)) {
      res.status(400).json({ error: '用户名只能包含字母、数字、下划线，长度2-20' })
      return
    }
    const users = readUsers(usersPath)
    if (users.find(u => u.username === username)) {
      res.status(409).json({ error: '用户名已存在' })
      return
    }
    const passwordHash = await bcrypt.hash(password, 10)
    const user: UserRecord = { id: randomUUID(), username, passwordHash, createdAt: Date.now() }
    users.push(user)
    writeUsers(usersPath, users)

    // Create user data directory
    const userDir = resolve(APP_ROOT, 'data', 'users', username)
    if (!existsSync(userDir)) mkdirSync(userDir, { recursive: true })

    const token = jwt.sign({ id: user.id, username }, JWT_SECRET, { expiresIn: '30d' })
    res.json({ token, username })
  })

  router.post('/auth/login', async (req, res) => {
    const { username, password } = req.body
    if (!username?.trim() || !password?.trim()) {
      res.status(400).json({ error: '用户名和密码不能为空' })
      return
    }
    const users = readUsers(usersPath)
    const user = users.find(u => u.username === username)
    if (!user) {
      res.status(401).json({ error: '用户名或密码错误' })
      return
    }
    const ok = await bcrypt.compare(password, user.passwordHash)
    if (!ok) {
      res.status(401).json({ error: '用户名或密码错误' })
      return
    }
    const token = jwt.sign({ id: user.id, username }, JWT_SECRET, { expiresIn: '30d' })
    res.json({ token, username })
  })

  router.get('/auth/me', (req, res) => {
    const header = req.headers.authorization
    if (!header?.startsWith('Bearer ')) { res.status(401).json({ error: '未登录' }); return }
    const token = header.slice(7)
    try {
      const payload = jwt.verify(token, JWT_SECRET) as { id: string; username: string }
      res.json({ username: payload.username })
    } catch {
      res.status(401).json({ error: 'Token 无效' })
    }
  })

  return router
}
