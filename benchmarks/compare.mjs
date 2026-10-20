import { spawn, spawnSync } from 'node:child_process'
import { createRequire } from 'node:module'
import { readFile, writeFile, mkdir } from 'node:fs/promises'
import path from 'node:path'
import { fileURLToPath } from 'node:url'

if (process.argv.includes('--help')) {
  console.log('Set DEEPSEEK_API_KEY, CITEWEAVE_ENDPOINT, CITEWEAVE_ACCESS_TOKEN and BENCH_MODEL_READY_URL. Optional: BENCH_PREWARM_COMMAND, BENCH_REPEATS=2, BENCH_OUTPUT, BENCH_CASES, BENCH_MODEL_READY_TOKEN. Then node benchmarks/compare.mjs. Readiness/prewarm occurs before the turn timer.')
  process.exit(0)
}
const root = path.dirname(fileURLToPath(import.meta.url))
const require = createRequire(new URL('../package.json', import.meta.url))
for (const name of ['DEEPSEEK_API_KEY', 'CITEWEAVE_ENDPOINT', 'BENCH_MODEL_READY_URL']) {
  if (!process.env[name]) throw new Error(`Set ${name} before running the comparison`)
}
const cli = path.join(path.dirname(require.resolve('@deepseek-ai/dsh/package.json')), 'lib/bin.js')
const plugin = fileURLToPath(new URL('../index.js', import.meta.url))
const cases = JSON.parse(await readFile(process.env.BENCH_CASES || new URL('./cases.json', import.meta.url)))
const output = path.resolve(process.env.BENCH_OUTPUT || path.join(root, 'private-runs', new Date().toISOString().replaceAll(':', '-')))
await mkdir(path.join(output, 'workspace'), { recursive: true })
const modelPatch = path.join(output, 'model.patch.yml')
const pluginPatch = path.join(output, 'plugin.patch.yml')
await writeFile(modelPatch, `- id: llm-deepseek\n  config:\n    thinking: disabled\n    reasoningEffort: off\n    maxTokens: 2048\n    models:\n      - id: deepseek-flash\n        contextWindow: 1000000\n        maxTokens: 2048\n- id: session-title-llm\n  disabled: true\n`)
await writeFile(pluginPatch, `- insert:\n    - id: citeweave\n      name: '${plugin.replaceAll('\\', '/')}'\n      config:\n        endpoint: !!js process.env.CITEWEAVE_ENDPOINT\n        accessToken: !!js process.env.CITEWEAVE_ACCESS_TOKEN\n        maxImages: 3\n        timeoutMs: 300000\n`)
const env = { ...process.env, DSH_HOME: path.join(output, 'home'), DSH_TELEMETRY_DISABLED: '1' }
const results = []
async function ready() {
  const started = Date.now()
  if (process.env.BENCH_PREWARM_COMMAND) {
    const r = spawnSync(process.env.BENCH_PREWARM_COMMAND, { shell: true, encoding: 'utf8', timeout: 180000 })
    if (r.status !== 0) throw new Error('Model prewarm command failed; trial not timed')
  }
  const response = await fetch(process.env.BENCH_MODEL_READY_URL, {
    headers: process.env.BENCH_MODEL_READY_TOKEN ? { Authorization: `Bearer ${process.env.BENCH_MODEL_READY_TOKEN}` } : {},
    signal: AbortSignal.timeout(10000),
  })
  await response.body?.cancel()
  if (!response.ok) throw new Error('The model is not ready; trial not timed')
  return { checkedAt: new Date().toISOString(), ready: true, excludedPrewarmSeconds: (Date.now() - started) / 1000 }
}
async function run(item, enabled, repeat) {
  const id = `${item.id}-${enabled ? 'on' : 'off'}-r${repeat}`
  const readiness = await ready()
  const started = Date.now()
  let raw = '', stderr = '', pending = '', turnStart, turnEnd, firstText
  const events = []
  const args = [cli, 'headless', '--patch', modelPatch, ...(enabled ? ['--patch', pluginPatch] : []), '--json', item.prompt]
  const exitCode = await new Promise((resolve, reject) => {
    const child = spawn(process.execPath, args, { cwd: path.join(output, 'workspace'), env, stdio: ['ignore', 'pipe', 'pipe'] })
    const timeout = setTimeout(() => { child.kill(); reject(new Error('Trial exceeded eight minutes')) }, 480000)
    child.stdout.on('data', b => {
      raw += b.toString(); pending += b.toString()
      let index
      while ((index = pending.indexOf('\n')) >= 0) {
        const line = pending.slice(0, index); pending = pending.slice(index + 1)
        try {
          const event = JSON.parse(line), now = Date.now()
          events.push({ observedAtMs: now, event })
          if (event.type === 'status' && event.phase === 'turn_start') turnStart ??= now
          if (event.type === 'status' && event.phase === 'turn_end') turnEnd = now
          if (event.type === 'text') firstText ??= now
        } catch { /* Non-JSON launcher diagnostics stay in the raw output. */ }
      }
    })
    child.stderr.on('data', b => { stderr += b.toString() })
    child.on('error', reject)
    child.on('exit', code => { clearTimeout(timeout); resolve(code) })
  })
  const final = events.findLast(x => x.event.type === 'final')?.event.text || ''
  const links = [...final.matchAll(/(!?)\[[^\]]*\]\(([^)]+)\)/g)]
  const summary = {
    id, case: item.id, enabled, repeat, prompt: item.prompt, readiness, exitCode,
    turnSeconds: turnStart && turnEnd ? (turnEnd - turnStart) / 1000 : null,
    processSeconds: (Date.now() - started) / 1000,
    firstTextSeconds: turnStart && firstText ? (firstText - turnStart) / 1000 : null,
    completed: events.some(x => x.event.type === 'status' && x.event.phase === 'turn_end' && x.event.reason?.kind === 'completed'),
    tools: events.filter(x => x.event.type === 'tool_call').map(x => ({ ...x.event, seconds: ((events.find(y => y.event.type === 'tool_result' && y.event.callId === x.event.callId)?.observedAtMs ?? x.observedAtMs) - x.observedAtMs) / 1000 })),
    toolErrors: events.filter(x => x.event.type === 'tool_result' && x.event.status !== 'completed').map(x => x.event),
    imageCount: links.filter(x => x[1] === '!').length,
    sourceLinkCount: new Set(links.filter(x => !x[1] && /^https?:/.test(x[2])).map(x => x[2])).size,
    answer: final,
  }
  results.push(summary)
  await Promise.all([
    writeFile(path.join(output, `${id}.raw.jsonl`), raw),
    writeFile(path.join(output, `${id}.stderr.txt`), stderr),
    writeFile(path.join(output, `${id}.answer.md`), final),
    writeFile(path.join(output, `${id}.summary.json`), JSON.stringify(summary, null, 2)),
    writeFile(path.join(output, 'results.json'), JSON.stringify(results, null, 2)),
  ])
  console.log(JSON.stringify({ id, seconds: summary.turnSeconds, images: summary.imageCount, links: summary.sourceLinkCount, completed: summary.completed }))
}
for (let repeat = 1; repeat <= Number(process.env.BENCH_REPEATS || 2); repeat++) {
  for (const [index, item] of cases.entries()) {
    for (const enabled of ((index + repeat) % 2 === 0 ? [true, false] : [false, true])) await run(item, enabled, repeat)
  }
}
