import { Router } from 'express'

export function proxyRouter(): Router {
  const router = Router()

  const OCR_URL = process.env.OCR_URL || ''
  const OCR_KEY = process.env.OCR_KEY || ''
  // OCR_MODE: "native" = POST directly to OCR_URL with image_base64 field
  //           "openai"  = POST to OCR_URL/chat/completions with OpenAI chat format (default)
  const OCR_MODE = process.env.OCR_MODE || 'openai'
  const TTS_URL = process.env.TTS_URL || ''
  const TTS_KEY = process.env.TTS_KEY || ''
  const ASR_URL = process.env.ASR_URL || ''
  const ASR_KEY = process.env.ASR_KEY || ''

  // OCR
  router.post('/ocr', async (req, res) => {
    const { image } = req.body
    if (!image || !OCR_URL) {
      res.status(400).json({ error: 'image 或 OCR_URL 缺失' })
      return
    }
    try {
      let text: string
      if (OCR_MODE === 'native') {
        // Native mode: POST image_base64 directly to OCR_URL
        const resp = await fetch(OCR_URL, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${OCR_KEY}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({ image_base64: image }),
        })
        if (!resp.ok) throw new Error(`OCR HTTP ${resp.status}`)
        const data = await resp.json() as any
        text = data.result?.trim() ?? ''
      } else {
        // OpenAI-compatible mode: POST to OCR_URL/chat/completions
        const resp = await fetch(`${OCR_URL}/chat/completions`, {
          method: 'POST',
          headers: {
            'Authorization': `Bearer ${OCR_KEY}`,
            'Content-Type': 'application/json',
          },
          body: JSON.stringify({
            model: 'ocr2.0',
            messages: [{
              role: 'user',
              content: [
                { type: 'image_url', image_url: { url: `data:image/png;base64,${image}` } },
                { type: 'text', text: '请识别图片中的题目文字，完整输出，不要添加任何解释。' },
              ],
            }],
            max_tokens: 4096,
          }),
        })
        if (!resp.ok) throw new Error(`OCR HTTP ${resp.status}`)
        const data = await resp.json() as any
        text = data.choices[0].message.content.trim()
      }
      res.json({ text })
    } catch (e: any) {
      res.status(502).json({ error: e.message })
    }
  })

  // TTS
  router.post('/tts', async (req, res) => {
    let text = req.body.text || ''
    if (!text || !TTS_URL) {
      res.status(400).json({ error: 'text 或 TTS_URL 缺失' })
      return
    }
    // Clean text for TTS
    text = text
      .replace(/\$\$[\s\S]*?\$\$/g, '公式')
      .replace(/\$[^$\n]+\$/g, (m: string) =>
        m.slice(1, -1)
          .replace(/\\frac\{/g, '').replace(/\}\{/g, '分之').replace(/\}/g, '')
          .replace(/\\sqrt\{/g, '根号').replace(/\^2/g, '的平方')
          .replace(/=/g, '等于').replace(/\\times/g, '乘以')
      )
      .replace(/\*\*|#{1,6}\s*|<[^>]+>/g, '')
      .trim()

    try {
      const form = new URLSearchParams()
      form.append('text', text)
      form.append('prompt_text', '同学们好，今天我们来学习这道题目。')

      const resp = await fetch(`${TTS_URL}/tts/zero_shot`, {
        method: 'POST',
        headers: { 'Authorization': `Bearer ${TTS_KEY}` },
        body: form,
      })
      if (!resp.ok) throw new Error(`TTS HTTP ${resp.status}`)
      const buf = Buffer.from(await resp.arrayBuffer())
      res.set('Content-Type', 'audio/wav')
      res.send(buf)
    } catch (e: any) {
      res.status(502).json({ error: e.message })
    }
  })

  // ASR
  router.post('/asr', async (req, res) => {
    const audioData = req.body as Buffer
    if (!audioData?.length || !ASR_URL) {
      res.status(400).json({ error: 'audio 或 ASR_URL 缺失' })
      return
    }
    try {
      const boundary = `AudioBoundary${Date.now()}`
      const header = `--${boundary}\r\nContent-Disposition: form-data; name="file"; filename="audio.wav"\r\nContent-Type: audio/wav\r\n\r\n`
      const footer = `\r\n--${boundary}--\r\n`
      const body = Buffer.concat([
        Buffer.from(header),
        audioData,
        Buffer.from(footer),
      ])

      const resp = await fetch(`${ASR_URL}/transcribe`, {
        method: 'POST',
        headers: {
          'Content-Type': `multipart/form-data; boundary=${boundary}`,
          'Authorization': `Bearer ${ASR_KEY}`,
        },
        body,
      })
      if (!resp.ok) throw new Error(`ASR HTTP ${resp.status}`)
      const data = await resp.json() as any
      res.json({ text: data.text || '' })
    } catch (e: any) {
      res.status(502).json({ error: e.message })
    }
  })

  return router
}
