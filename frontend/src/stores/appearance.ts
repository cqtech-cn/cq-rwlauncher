/**
 * 外观自定义 store。
 *
 * 保存一份前端实时外观状态，并通过 applyAppearance() 把配置映射到
 * html 的 data-theme / data-density 属性与 CSS 变量（--panel-alpha / --bg-img）。
 * SettingsView 修改外观后调用 applyAppearance 即时预览，App.vue 启动时读取 config 应用。
 */
import { ref } from 'vue'

export interface AppearanceState {
  theme: 'light' | 'dark' | 'mizuiro'
  density: 'comfortable' | 'compact'
  background_image: string // 绝对路径，空 = 无
  panel_opacity: number // 0-100
  home_modules: { launch: boolean; download: boolean }
}

export const THEME_OPTIONS: Array<{
  id: 'light' | 'dark' | 'mizuiro'
  label: string
  description: string
}> = [
  { id: 'light', label: '浅色', description: '简洁白底，黑灰强调' },
  { id: 'dark', label: '深色', description: '暗色背景，长时间看代码眼睛不累' },
  { id: 'mizuiro', label: '水色系', description: '日系亚文化水蓝调，带薰衣草和樱花装饰' },
]

const defaults: AppearanceState = {
  theme: 'light',
  density: 'comfortable',
  background_image: '',
  panel_opacity: 100,
  home_modules: { launch: true, download: true },
}

/** 全局外观状态（模块级 ref，跨组件共享） */
export const appearance = ref<AppearanceState>({ ...defaults })

/**
 * 背景图 data URI（base64 内嵌）。
 * pywebview 以 localhost HTTP 加载页面，file:// 与相对路径引用本地图片都会失败，
 * 所以渲染背景一律使用后端生成的 data URI；路径只用于 config 持久化。
 */
export const backgroundDataUri = ref('')

/** 把任意后端配置清洗成合法外观状态 */
export function sanitizeAppearance(raw: any): AppearanceState {
  const r = (raw && typeof raw === 'object' ? raw : {}) as Record<string, any>
  const themeId = r.theme
  const theme: AppearanceState['theme'] =
    themeId === 'dark' ? 'dark' :
    themeId === 'mizuiro' ? 'mizuiro' :
    'light'
  const safe: AppearanceState = {
    ...defaults,
    theme,
    density: r.density === 'compact' ? 'compact' : 'comfortable',
    background_image: typeof r.background_image === 'string' ? r.background_image : '',
    panel_opacity: Math.max(0, Math.min(100, Number(r.panel_opacity) || 100)),
    home_modules: {
      launch: r.home_modules?.launch !== false,
      download: r.home_modules?.download !== false,
    },
  }
  return safe
}

/** 本地绝对路径 → file:/// URL（浏览器调试模式兜底） */
function toFileUrl(p: string): string {
  if (/^file:\/\//i.test(p)) return p
  return 'file:///' + p.replace(/\\/g, '/')
}

/** 当前背景图的 Blob URL（避免把大 data URI 塞进 CSS 变量）。 */
let _bgBlobUrl: string | null = null

/** base64 data URI → Blob URL */
function dataUriToBlobUrl(uri: string): string {
  const comma = uri.indexOf(',')
  const meta = uri.slice(0, comma)
  const mime = (meta.match(/data:([^;]+)/) || [])[1] || 'image/png'
  const bin = atob(uri.slice(comma + 1))
  const bytes = new Uint8Array(bin.length)
  for (let i = 0; i < bin.length; i++) bytes[i] = bin.charCodeAt(i)
  return URL.createObjectURL(new Blob([bytes], { type: mime }))
}

/**
 * 设置 --bg-img。
 * data URI 可能远超 Chromium 的 CSS 自定义属性长度上限（约 128KB），
 * 会静默截断导致图片损坏，因此统一先转成 Blob URL 再写入变量。
 */
function setBgImage(root: HTMLElement, uri: string) {
  if (_bgBlobUrl) {
    URL.revokeObjectURL(_bgBlobUrl)
    _bgBlobUrl = null
  }
  if (!uri) {
    root.style.setProperty('--bg-img', 'none')
    return
  }
  if (uri.startsWith('data:')) {
    try {
      _bgBlobUrl = dataUriToBlobUrl(uri)
      root.style.setProperty('--bg-img', `url("${_bgBlobUrl}")`)
      return
    } catch {
      // 转换失败（极小概率）则回退直接写入
    }
  }
  root.style.setProperty('--bg-img', `url("${uri}")`)
}

/** 应用外观到 document（即时生效） */
export function applyAppearance(a: Partial<AppearanceState>) {
  appearance.value = { ...appearance.value, ...a }
  const s = appearance.value
  const root = document.documentElement

  root.setAttribute('data-theme', s.theme)
  root.setAttribute('data-density', s.density)
  root.style.setProperty('--panel-alpha', `${s.panel_opacity ?? 100}%`)

  // 背景图：优先 data URI（Blob URL 化）；其次旧路径形式（浏览器调试模式可用）
  if (backgroundDataUri.value) {
    setBgImage(root, backgroundDataUri.value)
  } else if (s.background_image) {
    setBgImage(root, toFileUrl(s.background_image))
  } else {
    setBgImage(root, '')
  }
}

/** 更新背景图（路径 + data URI 一起设置），立即应用 */
export function setBackground(path: string, dataUri: string) {
  backgroundDataUri.value = dataUri
  appearance.value.background_image = path
  applyAppearance({ background_image: path })
}

/** 移除背景图，立即应用 */
export function clearBackground() {
  backgroundDataUri.value = ''
  appearance.value.background_image = ''
  applyAppearance({ background_image: '' })
}
