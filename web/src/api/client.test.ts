import { api, ApiError, hasToken, login, setOnLogout } from './client'

const json = (status: number, body?: unknown) => new Response(body === undefined ? null : JSON.stringify(body), { status })

afterEach(() => vi.unstubAllGlobals())

test('401 -> refresh uma vez -> repete com o novo token', async () => {
  const calls: [string, string | undefined][] = []
  const fetchMock = vi.fn(async (url: string, init: RequestInit) => {
    const auth = (init.headers as Record<string, string>)?.Authorization
    calls.push([url, auth])
    if (url === '/auth/login') return json(200, { access_token: 'old' })
    if (url === '/auth/refresh') return json(200, { access_token: 'new' })
    return auth === 'Bearer new' ? json(200, { ok: 1 }) : json(401, { detail: 'invalid_token' })
  })
  vi.stubGlobal('fetch', fetchMock)
  await login('a@b.c', 'x')
  expect(await api('GET', '/accounts')).toEqual({ ok: 1 })
  expect(calls.map((c) => c[0])).toEqual(['/auth/login', '/accounts', '/auth/refresh', '/accounts'])
})

test('refresh em paralelo é compartilhado', async () => {
  let refreshes = 0
  vi.stubGlobal('fetch', async (url: string, init: RequestInit) => {
    if (url === '/auth/refresh') { refreshes++; return json(200, { access_token: 't2' }) }
    return (init.headers as Record<string, string>)?.Authorization === 'Bearer t2' ? json(200, []) : json(401)
  })
  await Promise.all([api('GET', '/a'), api('GET', '/b')])
  expect(refreshes).toBe(1)
})

test('refresh falho -> logout e erro 401', async () => {
  const out = vi.fn()
  setOnLogout(out)
  vi.stubGlobal('fetch', async () => json(401, { detail: 'invalid_refresh' }))
  await expect(api('GET', '/accounts')).rejects.toBeInstanceOf(ApiError)
  expect(out).toHaveBeenCalled()
  expect(hasToken()).toBe(false)
})

test('nunca grava token em localStorage', async () => {
  vi.stubGlobal('fetch', async () => json(200, { access_token: 'secret' }))
  await login('a@b.c', 'x')
  expect(JSON.stringify({ ...localStorage })).not.toContain('secret')
})
