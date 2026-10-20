import assert from 'node:assert/strict'
import { once } from 'node:events'
import { createServer } from 'node:http'
import { mkdtemp, mkdir, readFile, rm, writeFile } from 'node:fs/promises'
import { createRequire } from 'node:module'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { test } from 'node:test'
import { Context } from '@deepseek-ai/cordis'
import Loader from '@deepseek-ai/cordis-plugin-loader'
import { mountRootInclude, readProfilePatches } from '@deepseek-ai/dsh-app-boot'
import LocalAttachmentStore from '@deepseek-ai/dsh-attachment-local'
import ConfigEditor from '@deepseek-ai/dsh-config-editor'
import SettingsForms from '@deepseek-ai/dsh-settings'
import { SystemPrompt } from '@deepseek-ai/dsh-system-prompt'
import { ToolRuntime } from '@deepseek-ai/dsh-tools'
import Schema from '@deepseek-ai/schemastery'

test('native settings forms redact secrets and apply live configuration without restarting the plugin', async t => {
  const home = await mkdtemp(join(tmpdir(), 'dsh-citeweave-settings-'))
  const ctx = new Context()
  const requests = []
  const servers = ['first', 'second'].map(name => createServer(async (request, response) => {
    let body = ''
    for await (const chunk of request) body += chunk
    const input = JSON.parse(body)
    requests.push({ name, authorization: request.headers.authorization, input })
    if (input.query === 'slow') return
    response.setHeader('Content-Type', 'application/json')
    response.end(JSON.stringify({ query: input.query, sources: [], images: [], retrieval_errors: [] }))
  }))
  t.after(async () => {
    await ctx.fiber.dispose()
    for (const server of servers) {
      server.closeAllConnections()
      await new Promise(resolve => server.close(resolve))
    }
    await rm(home, { recursive: true, force: true })
  })
  for (const server of servers) {
    server.listen(0, '127.0.0.1')
    await once(server, 'listening')
  }
  const endpoints = servers.map(server => `http://127.0.0.1:${server.address().port}`)
  const dir = join(home, 'profiles/settings-ci')
  await mkdir(dir, { recursive: true })
  const patchPath = join(dir, 'cordis.patch.yml')
  const rootPath = join(dir, 'cordis.yml')
  await writeFile(join(dir, 'package.json'), JSON.stringify({ private: true, dsh: { profile: { bundles: [] } } }))
  await writeFile(rootPath, '[]\n')
  await writeFile(patchPath, JSON.stringify([{ insert: [{ id: 'citeweave', name: new URL('../index.js', import.meta.url).href, config: { endpoint: endpoints[0], accessToken: 'original-secret', maxImages: 3, timeoutMs: 5000 } }] }]))
  const profile = { name: 'settings-ci', dir, patchPath, home, cwd: dir, installAnchor: createRequire(import.meta.url).resolve('@deepseek-ai/dsh/package.json'), startedBundles: [], overlays: [], telemetryDisabledEnv: '1' }
  ctx.provide('profileContext', profile)
  ctx.provide('fs', { processPathFromHostPath: path => path })
  await ctx.plugin(Loader).await()
  await ctx.plugin(LocalAttachmentStore, { dshHome: home }).await()
  await ctx.plugin(SystemPrompt, { includeRuntimeContext: false }).await()
  await ctx.plugin(ToolRuntime).await()
  await ctx.plugin(ConfigEditor).await()
  await ctx.plugin(SettingsForms).await()
  await mountRootInclude(ctx, rootPath, readProfilePatches('dsh', profile))
  await ctx.loader.await()

  const entry = ctx.configEditor.entries().find(entry => entry.options.id === 'citeweave')
  assert.ok(entry?.fiber, 'real Loader must mount a configurable CiteWeave entry')
  const fiber = entry.fiber
  const descriptor = ctx.settings.describe({ redactSecrets: true }).find(row => row.ns === 'citeweave')
  assert.ok(descriptor?.autoGenerate)
  assert.equal(descriptor.applies, 'live')
  assert.deepEqual(Object.keys(new Schema(descriptor.schema).dict).sort(), ['accessToken', 'endpoint', 'maxImages', 'timeoutMs'])
  assert.equal(descriptor.value.endpoint, endpoints[0])
  assert.equal(descriptor.value.accessToken, undefined)
  assert.ok(descriptor.secrets.some(secret => secret.path.join('.') === 'accessToken' && secret.set))
  assert.ok(!JSON.stringify(descriptor).includes('original-secret'))
  const call = query => ctx.tools.execute({ name: 'citeweave_search', arguments: { query }, callId: `settings-${requests.length}`, signal: new AbortController().signal })
  assert.equal((await call('before settings')).isError, false)
  assert.deepEqual(requests[0], { name: 'first', authorization: 'Bearer original-secret', input: { query: 'before settings', verify_images: true, refresh: false, max_images: 3 } })

  await ctx.settings.mutate('citeweave', [
    { op: 'set', path: ['endpoint'], value: endpoints[1] },
    { op: 'set', path: ['accessToken'], value: 'replacement-secret' },
    { op: 'set', path: ['maxImages'], value: 1 },
    { op: 'set', path: ['timeoutMs'], value: 100 },
  ], descriptor.revision)
  assert.strictEqual(entry.fiber, fiber, 'volatile edits must preserve the plugin fiber')
  assert.equal(ctx.tools.get('citeweave_search').timeoutMs, 100)
  assert.equal((await call('after settings')).isError, false)
  assert.deepEqual(requests[1], { name: 'second', authorization: 'Bearer replacement-secret', input: { query: 'after settings', verify_images: true, refresh: false, max_images: 1 } })
  const updated = ctx.settings.describe({ redactSecrets: true }).find(row => row.ns === 'citeweave')
  assert.equal(updated.value.timeoutMs, 100)
  assert.ok(!JSON.stringify(updated).includes('replacement-secret'))
  await ctx.settings.update('citeweave', { maxImages: 2 }, updated.revision)
  assert.strictEqual(entry.fiber, fiber)
  assert.equal((await call('preserve secret')).isError, false)
  assert.equal(requests[2].authorization, 'Bearer replacement-secret')
  assert.equal(requests[2].input.max_images, 2)
  assert.match(await readFile(patchPath, 'utf8'), /replacement-secret/)
  const timedOut = await call('slow')
  assert.equal(timedOut.isError, true, 'new timeout must cancel a stalled backend request')
  assert.strictEqual(entry.fiber, fiber)
})
