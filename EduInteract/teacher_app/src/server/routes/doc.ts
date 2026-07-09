import { Router, type Request, type Response } from 'express'
import { resolve } from 'path'
import { existsSync } from 'fs'

export function docRouter(ROOT: string): Router {
  const router = Router()

  router.get('/*filepath', (req: Request, res: Response) => {
    const raw = (req.params as any).filepath
    const fp = Array.isArray(raw) ? raw.join('/') : (raw || '')
    const filepath = resolve(ROOT, fp)
    if (!existsSync(filepath)) {
      res.status(404).json({ error: 'not found' })
      return
    }
    res.sendFile(filepath)
  })

  return router
}

