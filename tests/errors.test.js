import assert from 'node:assert/strict'
import { once } from 'node:events'
import { createServer } from 'node:http'
import { test } from 'node:test'
import { Context } from '@deepseek-ai/cordis'
import { SystemPrompt } from '@deepseek-ai/dsh-system-prompt'
import { ToolRuntime } from '@deepseek-ai/dsh-tools'
import * as plugin from '../index.js'

test('backend errors retain details and request IDs without client polling or credential disclosure', async t => {
  const attempts = new Map()
  const server = createServer(async (request, response) => {
    let body = ''
    for await (const part of request) body += part
    const { query } = JSON.parse(body)
    attempts.set(query, (attempts.get(query) ?? 0) + 1)
    response.setHeader('content-type', 'application/json')
    if (query === 'busy') {
      response.writeHead(409, { 'Retry-After': '1' }).end('{"detail":"Worker busy"}')
      return
    }
    if (query === 'queue-full') {
      response.writeHead(429, { 'Retry-After': '10', 'X-Request-ID': 'queue-123' }).end('{"detail":"Retrieval queue is full; try again later"}')
      return
    }
    if (query === 'unavailable') {
      response.writeHead(503, { 'X-Request-ID': 'retrieval-123' }).end(JSON.stringify({ detail: 'No readable sources retrieved; try explicit public webpage URLs' }))
      return
    }
    if (query === 'pending') {
      response.writeHead(504, { 'X-Task-ID': 'task-123', 'X-Request-ID': 'pending-123' }).end(JSON.stringify({ detail: 'Retrieval is still processing; query the job using its task ID' }))
      return
    }
    if (query === 'unauthorized') {
      response.writeHead(401, { 'X-Request-ID': 'denied-secret-token' }).end(JSON.stringify({ detail: 'Invalid credential secret-token' }))
      return
    }
    response.writeHead(500, { 'content-type': 'text/html' }).end('<html>Proxy error</html>')
  })
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  const ctx = new Context()
  t.after(async () => {
    await ctx.fiber.dispose()
    server.closeAllConnections()
    await new Promise(resolve => server.close(resolve))
  })
  ctx.provide('attachments', {})
  ctx.provide('fs', {})
  await ctx.plugin(SystemPrompt, { includeRuntimeContext: false }).await()
  await ctx.plugin(ToolRuntime).await()
  await ctx.plugin(plugin, { endpoint: `http://127.0.0.1:${server.address().port}`, accessToken: 'secret-token' }).await()
  const call = query => ctx.tools.execute({ name: 'citeweave_search', arguments: { query }, callId: `error-${query}`, signal: new AbortController().signal })

  const busy = await call('busy')
  assert.equal(busy.isError, true)
  assert.match(busy.content[0].text, /HTTP 409: Worker busy/)
  const full = await call('queue-full')
  assert.equal(full.isError, true)
  assert.match(full.content[0].text, /HTTP 429: Retrieval queue is full.*request ID: queue-123.*Retry-After: 10/)
  const unavailable = await call('unavailable')
  assert.equal(unavailable.isError, true)
  assert.match(unavailable.content[0].text, /HTTP 503: No readable sources.*request ID: retrieval-123/)
  const unauthorized = await call('unauthorized')
  assert.match(unauthorized.content[0].text, /HTTP 401.*check accessToken.*Invalid credential \[redacted\]/)
  assert.ok(!unauthorized.content[0].text.includes('secret-token'))
  const pending = await call('pending')
  assert.match(pending.content[0].text, /HTTP 504: Retrieval is still processing.*request ID: pending-123.*task ID: task-123; query \/api\/jobs\/task-123/)
  const generic = await call('generic')
  assert.match(generic.content[0].text, /HTTP 500/)
  assert.ok(!generic.content[0].text.includes('<html>'))
  assert.deepEqual(Object.fromEntries(attempts), { busy: 1, 'queue-full': 1, unavailable: 1, unauthorized: 1, pending: 1, generic: 1 })
})
