/**
 * 账号服务可用性状态。
 *
 * 启动时探测一次账号服务，之后每 60 秒静默复查一次。
 * 供全局提示条与各页面消费：账号服务不可用时，提示条会显著提醒，
 * 但只影响「平台」渠道，模组下载仍可走「铁锈盒子」直连。
 */
import { ref, computed } from 'vue'
import { authApi } from '@/api/pywebview'

/** null = 尚未探测 / 探测中 */
export const accountReachable = ref<boolean | null>(null)
export const accountBaseUrl = ref('')
export const accountLastError = ref('')
export const accountCheckedAt = ref('')
/** 本次运行内用户是否已手动忽略提示 */
export const accountAlertDismissed = ref(false)
/** 是否正在探测 */
export const accountProbing = ref(false)

const RECHECK_INTERVAL_MS = 60_000
let timer: number | null = null

/** 提示条是否应该显示 */
export const showAccountAlert = computed(
  () => accountReachable.value === false && !accountAlertDismissed.value,
)

function stamp(): string {
  const d = new Date()
  const p = (n: number) => String(n).padStart(2, '0')
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}`
}

/** 探测账号服务可达性。silent=true 时不改变"探测中"标记（供定时复查使用） */
export async function probeAccount(silent = false): Promise<boolean> {
  if (!silent) accountProbing.value = true
  try {
    const st = await authApi.status().catch(() => null)
    if (st?.base_url) accountBaseUrl.value = st.base_url
    const h = await authApi.health()
    accountReachable.value = !!h.reachable
    accountLastError.value = h.reachable ? '' : h.error || ''
    if (h.reachable) accountAlertDismissed.value = false
    return !!h.reachable
  } catch (e: any) {
    accountReachable.value = false
    accountLastError.value = e?.message || ''
    return false
  } finally {
    accountCheckedAt.value = stamp()
    if (!silent) accountProbing.value = false
  }
}

/** 启动定时复查（重复调用安全） */
export function startAccountWatch() {
  if (timer !== null) return
  timer = window.setInterval(() => {
    void probeAccount(true)
  }, RECHECK_INTERVAL_MS)
}

export function stopAccountWatch() {
  if (timer !== null) {
    window.clearInterval(timer)
    timer = null
  }
}

/** 忽略本次提示（下次启动或下次探测恢复后重置） */
export function dismissAccountAlert() {
  accountAlertDismissed.value = true
}