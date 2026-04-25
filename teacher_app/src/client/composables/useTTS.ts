import { ref, type Ref } from 'vue'
import { apiFetch } from '../utils/api'

export interface TTSState {
  playingIndex: Ref<number>
  play: (text: string, index: number) => void
  stop: () => void
}

export function useTTS(): TTSState {
  const playingIndex = ref(-1)
  let currentAudio: HTMLAudioElement | null = null

  function stop() {
    if (currentAudio) {
      currentAudio.pause()
      currentAudio = null
    }
    playingIndex.value = -1
  }

  async function play(text: string, index: number) {
    stop()
    if (!text) return

    playingIndex.value = index

    try {
      const resp = await apiFetch('api/tts', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ text }),
      })
      if (!resp.ok) throw new Error('TTS failed')
      const blob = await resp.blob()
      const url = URL.createObjectURL(blob)
      currentAudio = new Audio(url)
      currentAudio.onended = () => { playingIndex.value = -1 }
      currentAudio.play()
    } catch {
      playingIndex.value = -1
    }
  }

  return { playingIndex, play, stop }
}
