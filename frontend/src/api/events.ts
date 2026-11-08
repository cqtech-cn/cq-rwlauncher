/**
 * 后端通过 window.evaluate_js 派发的自定义事件封装。
 */

export const RW_EVENTS = {
  PROGRESS: 'rw:download:progress',
  STATUS: 'rw:download:status',
  TOAST: 'rw:toast',
  INSTALLED_CHANGED: 'rw:installed:changed',
  BLOCKED: 'rw:blocked',
} as const

export interface ProgressEvent {
  task_id: string
  downloaded: number
  total: number   // 0 表示未知总大小
  speed?: number  // 字节/秒
}

export interface StatusEvent {
  task_id: string
  status: 'pending' | 'downloading' | 'extracting' | 'needs_confirm' | 'completed' | 'failed' | 'canceled'
  error?: string | null
  kind?: 'mod' | 'map'
  title?: string
  folder?: string
  top?: string
}

export interface ToastEvent {
  message: string
  kind: 'success' | 'error' | 'warning' | 'info'
}

export interface BlockedEvent {
  message: string
}

export interface InstalledChangedEvent {
  kind: 'mod' | 'map'
  task_id: string
}

export function on<T>(eventName: string, handler: (detail: T) => void): () => void {
  const listener = (e: Event) => handler((e as CustomEvent<T>).detail)
  window.addEventListener(eventName, listener)
  return () => window.removeEventListener(eventName, listener)
}
