import { ref, type Ref } from 'vue'
import { apiFetch } from '../utils/api'

export interface RecorderState {
  recording: Ref<boolean>
  startRecord: () => void
  stopRecord: () => Promise<string>
}

export function useRecorder(): RecorderState {
  const recording = ref(false)
  let mediaRecorder: MediaRecorder | null = null
  let audioChunks: Blob[] = []
  let resolveStop: ((text: string) => void) | null = null

  function startRecord() {
    audioChunks = []
    navigator.mediaDevices.getUserMedia({ audio: true })
      .then(stream => {
        mediaRecorder = new MediaRecorder(stream, { mimeType: 'audio/webm' })
        mediaRecorder.ondataavailable = (e) => {
          if (e.data.size > 0) audioChunks.push(e.data)
        }
        mediaRecorder.onstop = async () => {
          stream.getTracks().forEach(t => t.stop())
          recording.value = false

          const blob = new Blob(audioChunks, { type: 'audio/webm' })
          try {
            const resp = await apiFetch('api/asr', {
              method: 'POST',
              headers: { 'Content-Type': 'application/octet-stream' },
              body: blob,
            })
            const data = await resp.json()
            resolveStop?.(data.text || '')
          } catch {
            resolveStop?.('')
          }
        }
        mediaRecorder.start()
        recording.value = true
      })
      .catch(() => {
        resolveStop?.('')
      })
  }

  function stopRecord(): Promise<string> {
    return new Promise(resolve => {
      resolveStop = resolve
      if (mediaRecorder && mediaRecorder.state === 'recording') {
        mediaRecorder.stop()
      } else {
        resolve('')
      }
    })
  }

  return { recording, startRecord, stopRecord }
}
