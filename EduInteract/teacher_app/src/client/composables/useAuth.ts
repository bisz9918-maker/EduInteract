import { ref } from 'vue'
import { apiUrl } from '../utils/api'

export const currentUser = ref<string | null>(null)

export function getToken(): string | null {
  return localStorage.getItem('teacher_token')
}

export function isLoggedIn(): boolean {
  return !!getToken()
}

export async function login(username: string, password: string): Promise<void> {
  const resp = await fetch(apiUrl('api/auth/login'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const data = await resp.json()
  if (!resp.ok) throw new Error(data.error || '登录失败')
  localStorage.setItem('teacher_token', data.token)
  currentUser.value = data.username
}

export async function register(username: string, password: string): Promise<void> {
  const resp = await fetch(apiUrl('api/auth/register'), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ username, password }),
  })
  const data = await resp.json()
  if (!resp.ok) throw new Error(data.error || '注册失败')
  localStorage.setItem('teacher_token', data.token)
  currentUser.value = data.username
}

export function logout(): void {
  localStorage.removeItem('teacher_token')
  currentUser.value = null
}

export async function initAuth(): Promise<boolean> {
  const token = getToken()
  if (!token) return false
  try {
    const resp = await fetch(apiUrl('api/auth/me'), {
      headers: { Authorization: `Bearer ${token}` },
    })
    if (!resp.ok) { logout(); return false }
    const data = await resp.json()
    currentUser.value = data.username
    return true
  } catch {
    logout()
    return false
  }
}
