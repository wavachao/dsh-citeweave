window.__ModuleLoader__.load({
  id: 'dsh-citeweave',
  factory(require) {
    const { createElement: h, useState } = require('react')
    const { SettingsForm, SettingsValueField, SettingsSecretField, Button } = require('@deepseek-ai/dsh-client-ui-primitives')
    const messages = {
      en: {
        endpoint: 'Backend URL', endpointHint: 'Address reachable from Harness. Leave blank to use CITEWEAVE_ENDPOINT or http://127.0.0.1:8765.',
        accessToken: 'Access token', accessTokenHint: 'Leave blank to keep the saved token. Only enter a value to replace it.',
        secretHidden: 'Saved tokens are never displayed.', clearToken: 'Clear saved token', clearTokenHint: 'Clearing restores the environment token, if set.', clearStaged: 'The saved token will be cleared when you save.',
        timeoutMs: 'Request timeout (ms)', timeoutMsHint: 'Maximum time for retrieval and image downloads.',
        maxImages: 'Maximum images', maxImagesHint: 'Select between 1 and 8 images per search.',
        invalid: 'Enter a valid HTTP(S) URL or whole number within the allowed range.', overridden: 'Overridden', reset: 'Reset to default',
        unavailable: 'Enable CiteWeave to edit its settings.', readOnly: 'This profile is read-only.',
        save: 'Save', saving: 'Saving…', saveFailed: 'Settings could not be saved. Your edits have been kept; reopen this page if another window changed them.',
        description: 'Connect to a CiteWeave backend for sourced images. Changes apply to the next search; the GPU backend must already be running.',
      },
      zh: {
        endpoint: '后端地址', endpointHint: '填写 Harness 可访问的地址。留空使用 CITEWEAVE_ENDPOINT 或 http://127.0.0.1:8765。',
        accessToken: '访问令牌', accessTokenHint: '留空保留已保存的令牌，输入新值才会替换。',
        secretHidden: '已保存的令牌不会回显。', clearToken: '清除已保存令牌', clearTokenHint: '清除后仍会使用环境变量中的令牌（若已设置）。', clearStaged: '保存后将清除已保存令牌。',
        timeoutMs: '请求超时（毫秒）', timeoutMsHint: '网页检索与图片下载的总时间上限。',
        maxImages: '最大图片数', maxImagesHint: '每次检索选择 1–8 张图片。',
        invalid: '请填写有效的 HTTP(S) 地址或范围内的整数。', overridden: '已覆盖', reset: '恢复默认',
        unavailable: '请先启用 CiteWeave，再编辑配置。', readOnly: '当前配置档为只读。',
        save: '保存', saving: '保存中…', saveFailed: '保存失败，已保留修改。若其他窗口更改了配置，请重新打开此页面。',
        description: '连接 CiteWeave 后端，为回答提供可溯源配图。保存后下次检索生效；GPU 后端需提前启动。',
      },
    }
    const fields = ['endpoint', 'timeoutMs', 'maxImages']
    const numeric = field => field !== 'endpoint'
    function valid(field, text) {
      if (text === null || text.trim() === '') return true
      if (numeric(field)) {
        const value = Number(text)
        return Number.isInteger(value) && value >= 1 && value <= (field === 'maxImages' ? 8 : 2147483647)
      }
      try { return ['http:', 'https:'].includes(new URL(text.trim()).protocol) } catch { return false }
    }
    return {
      inject: ['slots', 'locale'],
      apply(ctx) {
        const ns = 'citeweave.settings'
        ctx.effect(() => ctx.locale.register(ns, messages))
        const t = ctx.locale.bind(ns)
        function Configuration({ view, form }) {
          const [drafts, setDrafts] = useState({})
          const [revision, setRevision] = useState()
          const [saving, setSaving] = useState(false)
          const [failed, setFailed] = useState(false)
          if (view === 'summary') return t('description')
          const state = form?.state
          const available = state?.status === 'ready'
          const writable = available && state.writable && !saving
          const dirty = Object.keys(drafts).length > 0
          const invalid = fields.some(field => Object.hasOwn(drafts, field) && !valid(field, drafts[field]))
          const discard = () => { setDrafts({}); setRevision(undefined); setFailed(false) }
          const edit = (field, text) => {
            if (!dirty) setRevision(state.revision)
            setFailed(false)
            setDrafts(previous => {
              const next = { ...previous, [field]: text }
              if (field === 'accessToken' && typeof text === 'string' && text.trim() === '') delete next[field]
              return next
            })
          }
          const save = async () => {
            setSaving(true)
            setFailed(false)
            try {
              const ops = Object.entries(drafts).map(([field, text]) => text === null || (field !== 'accessToken' && text.trim() === '')
                ? { op: 'unset', path: [field] }
                : { op: 'set', path: [field], value: fields.includes(field) && numeric(field) ? Number(text) : text.trim() })
              if (await form.mutate(ops, revision)) discard()
              else setFailed(true)
            } catch { setFailed(true) } finally { setSaving(false) }
          }
          return h(SettingsForm, {
            labels: Object.fromEntries(['unavailable', 'readOnly', 'save', 'saving', 'saveFailed'].map(key => [key, t(key)])),
            state: { available, writable: state?.writable ?? false, dirty, invalid, saving, failed },
            onSave: save, onDiscard: discard,
          },
          h('p', { style: { fontSize: 13, lineHeight: '20px', color: 'var(--dsw-alias-label-secondary)' } }, t('description')),
          ...fields.map(field => h(SettingsValueField, {
            key: field, id: `citeweave-${field}`, label: t(field), hint: t(`${field}Hint`),
            text: Object.hasOwn(drafts, field) ? drafts[field] ?? String(state?.base?.[field] ?? '') : String(state?.value?.[field] ?? ''),
            numeric: numeric(field), disabled: !writable,
            overridden: Object.hasOwn(drafts, field) ? drafts[field] !== null : Object.hasOwn(state?.user ?? {}, field),
            invalid: Object.hasOwn(drafts, field) && !valid(field, drafts[field]),
            overriddenLabel: t('overridden'), resetLabel: t('reset'), invalidLabel: t('invalid'),
            onEdit: text => edit(field, text), onReset: () => edit(field, null),
          })),
          h(SettingsSecretField, {
            id: 'citeweave-accessToken', label: t('accessToken'), hint: t('accessTokenHint'),
            text: drafts.accessToken ?? '', configured: false, stateLabel: t('secretHidden'),
            disabled: !writable, onEdit: text => edit('accessToken', text),
          }),
          h('div', null, h(Button, { variant: 'outline', size: 'sm', disabled: !writable, onClick: () => edit('accessToken', null) }, t('clearToken')),
            h('p', { style: { fontSize: 12, lineHeight: '18px', color: 'var(--dsw-alias-label-secondary)' } }, t(drafts.accessToken === null ? 'clearStaged' : 'clearTokenHint'))))
        }
        ctx.effect(() => ctx.slots.inject('plugins.row.config', () => ctx.slots.register({
          name: 'plugins.row.config', key: 'dsh-citeweave#citeweave', locale: ns,
        }, Configuration)))
      },
    }
  },
})
