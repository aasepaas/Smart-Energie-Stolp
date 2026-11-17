// API client (component 'API client' in C4 3.1): the only way to the Frontend API.
//
// Demo version: there is no login form yet. The client logs in once with the demo
// account from .env.local (VITE_DEMO_EMAIL, VITE_DEMO_PASSWORD), keeps the access token
// in memory and adds it to every request. On a 401 (expired token) it logs in again
// once. The Authentication component replaces this with a real login later.

import { texts } from '../texts'
import type { ImportRecord, SimultaneityResponse, UploadAccepted } from './types'

const BASE = '/v1'

export class ApiError extends Error {
  readonly status: number

  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

let token: string | null = null
let pendingLogin: Promise<string> | null = null

/** Forget the token (used by the tests). */
export function resetSession(): void {
  token = null
  pendingLogin = null
}

async function login(): Promise<string> {
  const email = import.meta.env.VITE_DEMO_EMAIL
  const password = import.meta.env.VITE_DEMO_PASSWORD
  if (!email || !password) throw new ApiError(0, texts.errors.noDemoAccount)
  const response = await send(`${BASE}/auth/login`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ email, password }),
  })
  if (response.status === 401) throw new ApiError(401, texts.errors.loginFailed)
  if (!response.ok) throw new ApiError(response.status, await errorMessage(response))
  const body = (await response.json()) as { access_token: string }
  return body.access_token
}

/** One login at a time, shared by all requests that need a token. */
function accessToken(): Promise<string> {
  if (token) return Promise.resolve(token)
  pendingLogin ??= login()
    .then((value) => (token = value))
    .finally(() => (pendingLogin = null))
  return pendingLogin
}

export async function request<T>(path: string, init: RequestInit = {}): Promise<T> {
  for (let attempt = 0; ; attempt++) {
    const bearer = await accessToken()
    const response = await send(`${BASE}${path}`, {
      ...init,
      headers: { ...(init.headers as Record<string, string>), Authorization: `Bearer ${bearer}` },
    })
    if (response.status === 401 && attempt === 0) {
      token = null // expired: log in again and retry once
      continue
    }
    if (!response.ok) throw new ApiError(response.status, await errorMessage(response))
    return (response.status === 204 ? undefined : await response.json()) as T
  }
}

async function send(url: string, init: RequestInit): Promise<Response> {
  try {
    return await fetch(url, init)
  } catch {
    throw new ApiError(0, texts.errors.unreachable)
  }
}

async function errorMessage(response: Response): Promise<string> {
  if ([502, 503, 504].includes(response.status) && !response.headers.get('content-type')?.includes('json')) {
    return texts.errors.unreachable // the dev proxy cannot reach the Frontend API
  }
  try {
    const body = (await response.json()) as { detail?: unknown }
    if (typeof body.detail === 'string') return body.detail
    if (Array.isArray(body.detail)) {
      return body.detail.map((item: { msg?: string }) => item.msg ?? String(item)).join('; ')
    }
  } catch {
    // not JSON
  }
  return texts.errors.generic(response.status)
}

// ---------- Endpoints used by the admin page ----------

export const api = {
  simultaneity(start: Date, end: Date, bucket: 'quarter' | 'hour' | 'day' | 'month' = 'day') {
    const query = new URLSearchParams({ start: start.toISOString(), end: end.toISOString(), bucket })
    return request<SimultaneityResponse>(`/simultaneity?${query}`)
  },

  imports(limit = 10) {
    return request<ImportRecord[]>(`/uploads?limit=${limit}`)
  },

  importStatus(importId: string) {
    return request<ImportRecord>(`/uploads/${encodeURIComponent(importId)}`)
  },

  upload(file: File) {
    const form = new FormData()
    form.append('file', file)
    return request<UploadAccepted>('/uploads', { method: 'POST', body: form })
  },
}
