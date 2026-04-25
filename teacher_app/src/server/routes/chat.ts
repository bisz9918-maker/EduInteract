import { Router } from 'express'

export function chatRouter(): Router {
  const router = Router()

  const API_BASE = process.env.CUSTOM_API_BASE || 'http://localhost:8001/v1'
  const API_KEY = process.env.CUSTOM_API_KEY || ''
  const DEFAULT_MODEL = process.env.TEACHER_MODEL_DEFAULT || process.env.TEACHER_MODEL || 'claude-sonnet-4-6'

  router.post('/chat', async (req, res) => {
    const { description, texts, history, message, current_scene, model: reqModel } = req.body
    const MODEL = reqModel || DEFAULT_MODEL
    const textsJoined = texts?.length ? texts.join('\n\n---\n\n') : '（暂无解析）'

    const systemPrompt = `你是一位经验丰富的教师助手，帮助教师准备课堂讲解材料。

题目：
${description || ''}

题目解析（供参考，包含所有讲解要点）：
${textsJoined}

当前教师正在查看第 ${current_scene || 1} 个图示。

请根据教师的问题，提供简洁、专业的备课建议。可以：
- 解释某个知识点
- 建议如何引导学生
- 补充例题或变式
- 对图示给出描述性说明

回复用中文，适当使用 Markdown 格式，数学公式用 $...$ 包裹。`

    const messages = [
      { role: 'system', content: systemPrompt },
      ...(history || []).map((m: any) => ({ role: m.role, content: m.content })),
      { role: 'user', content: message },
    ]

    res.writeHead(200, {
      'Content-Type': 'text/event-stream',
      'Cache-Control': 'no-cache',
      'Connection': 'keep-alive',
      'X-Accel-Buffering': 'no',
    })

    try {
      const resp = await fetch(`${API_BASE}/chat/completions`, {
        method: 'POST',
        headers: {
          'Authorization': `Bearer ${API_KEY}`,
          'Content-Type': 'application/json',
        },
        body: JSON.stringify({
          model: MODEL,
          messages,
          stream: true,
          max_tokens: 2048,
        }),
      })

      if (!resp.ok || !resp.body) {
        res.write(`data: ${JSON.stringify({ error: `HTTP ${resp.status}` })}\n\n`)
        res.end()
        return
      }

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          const chunk = line.slice(5).trim()
          if (chunk === '[DONE]') {
            res.write('data: [DONE]\n\n')
            continue
          }
          try {
            const parsed = JSON.parse(chunk)
            const delta = parsed.choices?.[0]?.delta?.content || ''
            if (delta) {
              res.write(`data: ${JSON.stringify({ text: delta })}\n\n`)
            }
          } catch {
            // skip
          }
        }
      }
    } catch (e: any) {
      res.write(`data: ${JSON.stringify({ error: e.message })}\n\n`)
    }

    res.end()
  })

  return router
}
