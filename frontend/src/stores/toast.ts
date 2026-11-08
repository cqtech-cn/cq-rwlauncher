/**
 * 全局 Toast 通知 store。
 * 后端通过 rw:toast 事件推送；前端任意位置可手动调用 push。
 *
 * 模块级状态：toasts 列表、初始化标志。
 * 暴露：useToastStore() 返回 { toasts, push, dismiss }。
 */
import { ref } from 'vue'
import { on, RW_EVENTS, type ToastEvent } from '@/api/events'

export interface ToastItem {
  id: number
  message: string
  kind: 'success' | 'error' | 'warning' | 'info'
  timeout: number
}

const toasts = ref<ToastItem[]>([])
let nextId = 1
let initialized = false

// 模块级 push / dismiss，确保事件回调能稳定访问
function push(message: string, kind: ToastItem['kind'] = 'info', timeout = 3000) {
  const id = nextId++
  toasts.value.push({ id, message, kind, timeout })
  setTimeout(() => {
    toasts.value = toasts.value.filter((t) => t.id !== id)
  }, timeout)
}

function dismiss(id: number) {
  toasts.value = toasts.value.filter((t) => t.id !== id)
}

function ensureInit() {
  if (initialized) return
  initialized = true
  on<ToastEvent>(RW_EVENTS.TOAST, (d) => push(d.message, d.kind))
}

export function useToastStore() {
  ensureInit()
  return { toasts, push, dismiss }
}
