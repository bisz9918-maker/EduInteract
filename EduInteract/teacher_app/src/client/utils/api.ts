import { ref } from 'vue'

/**
 * Build API URL that works behind reverse proxies with sub-paths.
 */
export function apiUrl(path: string): string {
  return new URL(path, window.location.href).href
}

/** Return Authorization header if token exists in localStorage */
export function authHeaders(): Record<string, string> {
  const token = localStorage.getItem('teacher_token')
  return token ? { Authorization: `Bearer ${token}` } : {}
}

/** fetch wrapper that auto-injects Authorization header */
export function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  return fetch(apiUrl(path), {
    ...init,
    headers: {
      ...(init.headers as Record<string, string> || {}),
      ...authHeaders(),
    },
  })
}

/** Global selected model (shared across composables) */
export const selectedModel = ref('')
/** Available models from server config */
export const modelList = ref<{ value: string; label: string }[]>([])

/** Fetch config from server and initialize selectedModel */
export async function fetchConfig() {
  try {
    const resp = await apiFetch('api/config')
    if (resp.ok) {
      const data = await resp.json()
      if (data.models?.length) modelList.value = data.models
      if (data.model && !selectedModel.value) selectedModel.value = data.model
    }
  } catch { /* ignore */ }
}
