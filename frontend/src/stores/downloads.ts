/**
 * 全局下载状态 store。
 * 后端通过 window CustomEvent 推送进度与状态变化。
 */
import { ref } from 'vue'
import { on, RW_EVENTS, type ProgressEvent, type StatusEvent } from '@/api/events'

export interface DownloadState {
  task_id: string
  status: 'pending' | 'downloading' | 'extracting' | 'completed' | 'failed' | 'canceled'
  downloaded: number
  total: number
  speed?: number  // 字节/秒
  error?: string | null
}

const downloads = ref<Map<string, DownloadState>>(new Map())
let initialized = false

function formatBytes(n: number): string {
  if (!n || n < 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let v = n
  let i = 0
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(v >= 10 || i === 0 ? 0 : 1)} ${units[i]}`
}

function formatSpeed(bps: number): string {
  if (!bps || bps <= 0) return ''
  return `${formatBytes(bps)}/s`
}

function ensureInit() {
  if (initialized) return
  initialized = true

  on<ProgressEvent>(RW_EVENTS.PROGRESS, (d) => {
    const cur = downloads.value.get(d.task_id)
    if (cur) {
      cur.downloaded = d.downloaded
      cur.total = d.total
      cur.speed = d.speed ?? cur.speed
    } else {
      downloads.value.set(d.task_id, {
        task_id: d.task_id,
        status: 'downloading',
        downloaded: d.downloaded,
        total: d.total,
        speed: d.speed,
      })
    }
  })

  on<StatusEvent>(RW_EVENTS.STATUS, (d) => {
    const cur = downloads.value.get(d.task_id)
    if (cur) {
      cur.status = d.status as DownloadState['status']
      cur.error = d.error ?? null
    } else {
      downloads.value.set(d.task_id, {
        task_id: d.task_id,
        status: d.status as DownloadState['status'],
        downloaded: 0,
        total: 0,
        error: d.error ?? null,
      })
    }
    // 完成 / 失败 / 取消 5 秒后清除
    if (d.status === 'completed' || d.status === 'failed' || d.status === 'canceled') {
      const id = d.task_id
      setTimeout(() => {
        if (downloads.value.get(id)?.status === d.status) {
          downloads.value.delete(id)
        }
      }, 5000)
    }
  })
}

export function useDownloadsStore() {
  ensureInit()
  const add = (task_id: string) => {
    downloads.value.set(task_id, {
      task_id,
      status: 'pending',
      downloaded: 0,
      total: 0,
    })
  }
  const get = (task_id: string) => downloads.value.get(task_id)
  const all = () => Array.from(downloads.value.values())
  const clearFinished = () => {
    for (const [k, v] of downloads.value) {
      if (v.status === 'completed' || v.status === 'failed' || v.status === 'canceled') {
        downloads.value.delete(k)
      }
    }
  }
  return { downloads, add, get, all, clearFinished }
}

export const fmt = { bytes: formatBytes, speed: formatSpeed }
