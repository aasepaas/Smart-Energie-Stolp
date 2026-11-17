import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest'
import { texts } from '../texts'
import { api, ApiError, request, resetSession } from './client'

function json(status: number, body: unknown): Response {
  return new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } })
}

const fetchMock = vi.fn<typeof fetch>()

beforeEach(() => {
  resetSession()
  fetchMock.mockReset()
  vi.stubGlobal('fetch', fetchMock)
})

afterEach(() => vi.unstubAllGlobals())

function calls(): string[] {
  return fetchMock.mock.calls.map(([url, init]) => `${init?.method ?? 'GET'} ${String(url)}`)
}

describe('request', () => {
  it('logs in once with the demo account and sends the token', async () => {
    fetchMock.mockImplementation(async (url) =>
      String(url).endsWith('/auth/login') ? json(200, { access_token: 'tok' }) : json(200, []),
    )
    await Promise.all([request('/uploads'), request('/uploads')])

    expect(calls()).toEqual(['POST /v1/auth/login', 'GET /v1/uploads', 'GET /v1/uploads'])
    const login = JSON.parse(String(fetchMock.mock.calls[0][1]?.body))
    expect(login).toEqual({ email: 'demo@example.org', password: 'demo password 123' })
    const headers = fetchMock.mock.calls[1][1]?.headers as Record<string, string>
    expect(headers.Authorization).toBe('Bearer tok')
  })

  it('logs in again once when the token has expired', async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, { access_token: 'old' }))
      .mockResolvedValueOnce(json(401, { detail: 'Token expired' }))
      .mockResolvedValueOnce(json(200, { access_token: 'new' }))
      .mockResolvedValueOnce(json(200, { ok: true }))

    await expect(request('/uploads')).resolves.toEqual({ ok: true })
    expect(calls()).toEqual(['POST /v1/auth/login', 'GET /v1/uploads', 'POST /v1/auth/login', 'GET /v1/uploads'])
  })

  it('turns API errors into a readable message', async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, { access_token: 'tok' }))
      .mockResolvedValueOnce(json(409, { detail: 'This file was imported before' }))
    const error = await request('/uploads', { method: 'POST' }).catch((e: unknown) => e)
    expect(error).toBeInstanceOf(ApiError)
    expect((error as ApiError).status).toBe(409)
  })

  it('reports a wrong demo account', async () => {
    fetchMock.mockResolvedValueOnce(json(401, { detail: 'Invalid email or password' }))
    await expect(request('/uploads')).rejects.toThrow(texts.errors.loginFailed)
  })

  it('reports an unreachable API', async () => {
    fetchMock.mockRejectedValueOnce(new TypeError('Failed to fetch'))
    await expect(request('/uploads')).rejects.toThrow(texts.errors.unreachable)
    fetchMock.mockResolvedValueOnce(new Response('', { status: 502 }))
    await expect(request('/uploads')).rejects.toThrow(texts.errors.unreachable)
  })
})

describe('api', () => {
  it('asks for simultaneity per day with UTC timestamps', async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, { access_token: 'tok' }))
      .mockResolvedValueOnce(json(200, { summary: {}, rows: [] }))
    await api.simultaneity(new Date('2026-03-15T23:00:00Z'), new Date('2026-04-12T22:00:00Z'))
    const url = new URL(String(fetchMock.mock.calls[1][0]), 'http://localhost')
    expect(url.pathname).toBe('/v1/simultaneity')
    expect(Object.fromEntries(url.searchParams)).toEqual({
      start: '2026-03-15T23:00:00.000Z',
      end: '2026-04-12T22:00:00.000Z',
      bucket: 'day',
    })
  })

  it('uploads the file as multipart form data', async () => {
    fetchMock
      .mockResolvedValueOnce(json(200, { access_token: 'tok' }))
      .mockResolvedValueOnce(json(202, { import_id: 'abc', status: 'running', file_name: 'a.csv' }))
    const file = new File(['meter_reference\n'], 'a.csv', { type: 'text/csv' })
    await expect(api.upload(file)).resolves.toMatchObject({ import_id: 'abc' })
    const body = fetchMock.mock.calls[1][1]?.body as FormData
    expect((body.get('file') as File).name).toBe('a.csv')
  })
})
