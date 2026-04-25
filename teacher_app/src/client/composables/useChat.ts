import { ref, type Ref } from 'vue'
import { apiUrl, apiFetch, selectedModel } from '../utils/api'

export interface ChatMessage {
  role: 'user' | 'assistant'
  content: string
}

export interface ChatState {
  messages: Ref<ChatMessage[]>
  chatOpen: Ref<boolean>
  streaming: Ref<boolean>
  toggleChat: () => void
  sendMessage: (
    message: string,
    context: { description: string; texts: string[]; currentScene: number }
  ) => void
}

export function useChat(): ChatState {
  const messages = ref<ChatMessage[]>([])
  const chatOpen = ref(false)
  const streaming = ref(false)

  function toggleChat() {
    chatOpen.value = !chatOpen.value
  }

  async function sendMessage(
    message: string,
    context: { description: string; texts: string[]; currentScene: number }
  ) {
    if (!message.trim() || streaming.value) return

    messages.value.push({ role: 'user', content: message })
    const assistantMsg: ChatMessage = { role: 'assistant', content: '' }
    messages.value.push(assistantMsg)
    streaming.value = true

    try {
      const resp = await fetch(apiUrl('api/chat'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({
          description: context.description,
          texts: context.texts,
          history: messages.value.slice(0, -2),
          message,
          current_scene: context.currentScene,
          ...(selectedModel.value ? { model: selectedModel.value } : {}),
        }),
      })

      if (!resp.body) throw new Error('No response body')

      const reader = resp.body.getReader()
      const decoder = new TextDecoder()
      let buffer = ''
      let fullText = ''

      while (true) {
        const { done, value } = await reader.read()
        if (done) break

        buffer += decoder.decode(value, { stream: true })
        const lines = buffer.split('\n')
        buffer = lines.pop() || ''

        for (const line of lines) {
          if (!line.startsWith('data:')) continue
          const chunk = line.slice(5).trim()
          if (chunk === '[DONE]') continue
          try {
            const j = JSON.parse(chunk)
            if (j.text) {
              fullText += j.text
              // Update the last message reactively
              messages.value[messages.value.length - 1] = {
                role: 'assistant',
                content: fullText,
              }
            }
          } catch {
            // skip
          }
        }
      }

      // Auto TTS
      if (fullText) autoTTS(fullText)
    } catch {
      messages.value[messages.value.length - 1] = {
        role: 'assistant',
        content: '请求失败，请重试。',
      }
    } finally {
      streaming.value = false
    }
  }

  async function autoTTS(text: string) {
    try {
      const resp = await fetch(apiUrl('api/tts'), {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })
      if (!resp.ok) return
      const blob = await resp.blob()
      const url = URL.createObjectURL(blob)
      new Audio(url).play()
    } catch {
      // ignore
    }
  }

  return { messages, chatOpen, streaming, toggleChat, sendMessage }
}
