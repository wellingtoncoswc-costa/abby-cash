// Token de acesso só em memória; o refresh vive no cookie httpOnly (path=/auth).
let token: string | null = null
let refreshing: Promise<boolean> | null = null
let onLogout: () => void = () => {}

export class ApiError extends Error {
  status: number
  detail: string
  constructor(status: number, detail: string) {
    super(detail)
    this.status = status
    this.detail = detail
  }
}

export const setOnLogout = (fn: () => void) => { onLogout = fn }
export const hasToken = () => token !== null

/** Renova o token (uma chamada por vez). */
export function refresh(): Promise<boolean> {
  refreshing ??= fetch('/auth/refresh', { method: 'POST', credentials: 'same-origin' })
    .then(async (r) => {
      if (!r.ok) return (token = null, false)
      token = ((await r.json()) as { access_token: string }).access_token
      return true
    })
    .catch(() => (token = null, false))
    .finally(() => { refreshing = null })
  return refreshing
}

async function send(method: string, path: string, body?: unknown): Promise<Response> {
  const headers: Record<string, string> = {}
  if (token) headers.Authorization = `Bearer ${token}`
  if (body !== undefined) headers['Content-Type'] = 'application/json'
  return fetch(path, { method, headers, credentials: 'same-origin', body: body === undefined ? undefined : JSON.stringify(body) })
}

/** 401 do token de acesso (não erro de credencial como invalid_credentials/totp_required). */
async function expiredAccess(r: Response): Promise<boolean> {
  const j = (await r.clone().json().catch(() => null)) as { detail?: unknown } | null
  return j?.detail === 'invalid_token' || j?.detail === 'not_authenticated'
}

async function raw(method: string, path: string, body?: unknown, retry = true): Promise<Response> {
  const bearer = token !== null
  let r = await send(method, path, body)
  if (r.status === 401 && retry && bearer && (await expiredAccess(r))) {
    if (await refresh()) r = await send(method, path, body)
    if (r.status === 401 && (await expiredAccess(r))) { token = null; onLogout() }
  }
  if (!r.ok) {
    const j = (await r.json().catch(() => null)) as { detail?: unknown } | null
    throw new ApiError(r.status, typeof j?.detail === 'string' ? j.detail : `http_${r.status}`)
  }
  return r
}

export async function api<T = unknown>(method: string, path: string, body?: unknown): Promise<T> {
  const r = await raw(method, path, body)
  return (r.status === 204 ? undefined : await r.json()) as T
}

export async function login(email: string, password: string, totp?: string) {
  const r = await send('POST', '/auth/login', { email, password, totp: totp || null })
  if (!r.ok) {
    const j = (await r.json().catch(() => null)) as { detail?: string } | null
    throw new ApiError(r.status, j?.detail ?? `http_${r.status}`)
  }
  token = ((await r.json()) as { access_token: string }).access_token
}

export async function logout() {
  await send('POST', '/auth/logout').catch(() => {})
  token = null
  onLogout()
}

export async function download(path: string, filename: string) {
  const blob = await (await raw('GET', path)).blob()
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

/** Lista com o total (X-Total-Count) para paginação. */
export async function apiPage<T>(path: string): Promise<{ items: T[]; total: number }> {
  const r = await raw('GET', path)
  return { items: (await r.json()) as T[], total: Number(r.headers.get('X-Total-Count') ?? 0) }
}

/** Baixa um arquivo autenticado como blob (o chamador cria/revoga a URL). */
export async function fetchBlob(path: string): Promise<Blob> {
  return (await raw('GET', path)).blob()
}
