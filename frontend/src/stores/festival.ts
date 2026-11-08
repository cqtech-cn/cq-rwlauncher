/**
 * 节日特别主题。
 *
 * 启动时向后端查询今天的节日状态（后端按"联网同步 → 本地缓存 → 内置兜底表"取数），
 * 命中法定假期时把 html 的 data-festival 属性设为节日标识，
 * 由 styles/global.css 里的节日配色块接管点缀色（文字与背景仍跟随当前主题）。
 */
import { ref, computed } from 'vue'
import { appApi } from '@/api/pywebview'

export type FestivalId =
  | ''
  | 'new-year'
  | 'spring-festival'
  | 'qingming'
  | 'labour-day'
  | 'dragon-boat'
  | 'mid-autumn'
  | 'national-day'

/** 当前生效的节日标识（空字符串 = 非节假日） */
export const festivalId = ref<FestivalId>('')
/** 节日展示名，如「中秋节」 */
export const festivalName = ref('')
/** 放假区间，如 2026-09-25 ~ 2026-09-27 */
export const festivalPeriod = ref('')
/** 数据来源：online=联网同步 / cache=本地缓存 / builtin=内置兜底 */
export const festivalSource = ref('')
/** 是否有节日主题在生效 */
export const festivalActive = computed(() => festivalId.value !== '')

/** 各节日的角标图形（SVG path，统一 16x16 视口，无 Emoji） */
const FESTIVAL_ICONS: Record<string, string> = {
  // 灯笼
  'new-year': 'M8 2.2c2.2 0 3.6 1.5 3.6 3.3 0 2-1.6 3.6-3.6 3.6S4.4 7.5 4.4 5.5C4.4 3.7 5.8 2.2 8 2.2Zm0 7.4v1.6M6.4 12.4h3.2M8 12.4v1.4',
  'spring-festival': 'M8 2.2c2.2 0 3.6 1.5 3.6 3.3 0 2-1.6 3.6-3.6 3.6S4.4 7.5 4.4 5.5C4.4 3.7 5.8 2.2 8 2.2Zm0 7.4v1.6M6.4 12.4h3.2M8 12.4v1.4',
  // 柳枝
  qingming: 'M8 2.4v11.2M8 5.6 5.2 3.4M8 5.6l2.8-2.2M8 9.2 5.6 7.4M8 9.2l2.4-1.8',
  // 齿轮
  'labour-day': 'M8 6.2a1.8 1.8 0 1 0 0 3.6 1.8 1.8 0 0 0 0-3.6Zm5.6 1.8-.9-.5.2-1-.8-.8-1 .2-.5-.9-1.2.3-.7-.7-.7.7-1.2-.3-.5.9-1-.2-.8.8.2 1-.9.5.9.5-.2 1 .8.8 1-.2.5.9 1.2-.3.7.7.7-.7 1.2.3.5-.9 1 .2.8-.8-.2-1 .9-.5Z',
  // 粽叶
  'dragon-boat': 'M8 1.8 4.6 6h6.8L8 1.8Zm0 4.2v3.4M4.2 11.4h7.6M5.4 13.6h5.2',
  // 月与桂
  'mid-autumn': 'M10.6 2.4a5.8 5.8 0 1 0 0 11.2 6.6 6.6 0 0 1 0-11.2Z',
  // 五角星
  'national-day': 'M8 1.9l1.6 3.5 3.8.4-2.8 2.6.8 3.7L8 10.3 4.6 12.1l.8-3.7L2.6 5.8l3.8-.4L8 1.9Z',
}

export function festivalIconPath(id: string): string {
  return FESTIVAL_ICONS[id] || FESTIVAL_ICONS['national-day']
}

/** 把节日标识写到 html 属性上，供 CSS 选择器生效 */
function applyFestival(id: string) {
  const root = document.documentElement
  if (id) {
    root.setAttribute('data-festival', id)
  } else {
    root.removeAttribute('data-festival')
  }
}

/** 查询并应用节日主题。失败时静默保持无节日状态，不影响启动。 */
export async function loadFestivalTheme(): Promise<void> {
  try {
    const r = await appApi.festivalTheme()
    const id = r?.active && r.theme ? (r.theme as FestivalId) : ''
    festivalId.value = id
    festivalName.value = r?.name || ''
    festivalPeriod.value = r?.period || ''
    festivalSource.value = r?.source || ''
    applyFestival(id)
  } catch {
    // 浏览器调试模式或后端异常：保持无节日配色
    festivalId.value = ''
    festivalName.value = ''
    festivalPeriod.value = ''
    festivalSource.value = ''
    applyFestival('')
  }
}

/** 用后端返回的配置即时应用（设置页切换开关时调用，避免重新联网） */
export function applyFestivalFromConfig(enabled: boolean) {
  if (!enabled) {
    festivalId.value = ''
    applyFestival('')
    return
  }
  void loadFestivalTheme()
}