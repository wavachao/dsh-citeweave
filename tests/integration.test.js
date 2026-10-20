import assert from 'node:assert/strict'
import { once } from 'node:events'
import { createServer } from 'node:http'
import { mkdtemp, readFile, rm } from 'node:fs/promises'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import { createRequire } from 'node:module'
import { pathToFileURL } from 'node:url'
import { test } from 'node:test'
import { Context } from '@deepseek-ai/cordis'
import { PluginPackages, createRuntimeResolution, loadProfileDirectory } from '@deepseek-ai/dsh-app-boot'
import LocalAttachmentStore from '@deepseek-ai/dsh-attachment-local'
import { SystemPrompt } from '@deepseek-ai/dsh-system-prompt'
import { ToolRuntime } from '@deepseek-ai/dsh-tools'
import { SESSION_LOG_FILENAME, streamSessionLogZip } from '@deepseek-ai/dsh-session-log-export'
import { unzipSync, strFromU8 } from 'fflate'
import { pack, run } from '../scripts/package.js'

// A valid RGBA PNG: real attachment-local decodes and verifies these bytes.
const png = Buffer.from('iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR4nGNgSDnxHwADwAIsn7GFYgAAAABJRU5ErkJggg==', 'base64')
const require = createRequire(import.meta.url)

test('release archive installs into Harness, returns native images, reopens, and exports complete media', { timeout: 180000 }, async t => {
  const directory = await mkdtemp(join(tmpdir(), 'dsh-citeweave integration '))
  const home = join(directory, 'home')
  const contexts = []
  const server = createServer(async (request, response) => {
    assert.equal(request.headers.authorization, 'Bearer integration-secret')
    if (request.url === '/cache/diagram.png') {
      response.setHeader('Content-Type', 'image/png')
      response.end(png)
      return
    }
    assert.equal(request.url, '/api/evidence')
    let input = ''
    for await (const chunk of request) input += chunk
    assert.equal(JSON.parse(input).query, 'Explain this diagram')
    response.setHeader('Content-Type', 'application/json')
    response.end(JSON.stringify({
      query: 'Explain this diagram',
      sources: [{ id: 's1', title: 'Diagram source', url: 'https://example.org/diagram', text: 'A sourced explanation.' }],
      images: [{ id: 'i1', source_id: 's1', url: 'https://example.org/diagram.png', render_url: '/cache/diagram.png', source_url: 'https://example.org/diagram', caption: 'Example diagram', caption_kind: 'visual_description' }],
      retrieval_errors: [],
    }))
  })
  server.listen(0, '127.0.0.1')
  await once(server, 'listening')
  t.after(async () => {
    for (const ctx of contexts.reverse()) await ctx.fiber.dispose()
    server.closeAllConnections()
    await new Promise(resolve => server.close(resolve))
    await rm(directory, { recursive: true, force: true })
  })

  const archive = await pack(directory)
  const cli = require.resolve('@deepseek-ai/dsh/lib/bin.js')
  const env = { ...process.env, DSH_HOME: home, DSH_TELEMETRY_DISABLED: '1', CI: '1' }
  await run(process.execPath, [cli, 'plugin', '--profile', 'citeweave-ci', 'add', archive.path], { env })
  const profile = join(home, 'profiles/citeweave-ci')
  const manifest = JSON.parse(await readFile(join(profile, 'package.json'), 'utf8'))
  assert.ok(manifest.dsh.profile.bundles.includes('dsh-citeweave'), 'CLI activates the shipped bundle')
  const config = await run(process.execPath, [cli, '--profile', 'citeweave-ci', '--dump-config'], { env })
  assert.match(config, /id: citeweave/)
  assert.match(config, /name: dsh-citeweave/)
  const ctx = new Context()
  contexts.push(ctx)
  // Harness owns the peers. Its official resolution service exposes them to
  // profile-installed packages without duplicating the host's service runtime.
  const installAnchor = require.resolve('@deepseek-ai/dsh/package.json')
  const resolution = await createRuntimeResolution({ home, installAnchor, profile: loadProfileDirectory('dsh', profile, installAnchor) })
  await ctx.plugin(PluginPackages, { resolution }).await()
  const installed = await import(pathToFileURL(join(profile, 'node_modules/dsh-citeweave/index.js')).href)
  ctx.provide('fs', { processPathFromHostPath: path => path })
  await ctx.plugin(LocalAttachmentStore, { dshHome: home }).await()
  await ctx.plugin(SystemPrompt, { includeRuntimeContext: false }).await()
  await ctx.plugin(ToolRuntime).await()
  await ctx.plugin(installed, { endpoint: `http://127.0.0.1:${server.address().port}`, accessToken: 'integration-secret' }).await()
  const result = await ctx.tools.execute({ name: 'citeweave_search', arguments: { query: 'Explain this diagram' }, callId: 'integration-call', signal: new AbortController().signal })
  assert.equal(result.isError, false, JSON.stringify(result))
  assert.equal(result.value.images.length, 1)
  const image = result.content.find(block => block.type === 'image')
  assert.ok(image, 'native content must declare an image, not just Markdown')
  assert.deepEqual(image.attachment, result.value.images[0].attachment)
  assert.equal(image.attachment.width, 1)
  assert.equal(image.attachment.height, 1)
  assert.match(result.content[0].text, /!\[Example diagram\]/)
  assert.match(result.content[0].text, /https:\/\/example.org\/diagram/)

  // Reopen the durable store in a fresh service, as a later Harness invocation does.
  const reopened = new Context()
  contexts.push(reopened)
  await reopened.plugin(LocalAttachmentStore, { dshHome: home }).await()
  const stored = await reopened.attachments.readImage(image.attachment)
  assert.deepEqual(Buffer.from(stored.data), png)
  assert.deepEqual(await readFile(reopened.attachments.imageHostPath(image.attachment)), png)

  // Use the official exporter on the native persisted tool/result content.
  const log = `${JSON.stringify({ type: 'tool/result', data: { message: { role: 'tool', content: result.content } } })}\n`
  const zip = streamSessionLogZip({ attachments: reopened.attachments }, log, 'integration-session', false, 6, new AbortController().signal)
  const files = unzipSync(new Uint8Array(await new Response(zip).arrayBuffer()))
  assert.equal(strFromU8(files[SESSION_LOG_FILENAME]), log)
  const media = Object.keys(files).filter(path => path.startsWith('media/'))
  assert.equal(media.length, 1, 'session archive must include the image bytes')
  assert.deepEqual(Buffer.from(files[media[0]]), png)
})
