<script setup lang="ts">
/**
 * 极简线性 SVG 图标库。
 * 全部用 currentColor，颜色由父级控制（严格遵循"无 emoji / 无紫蓝 / 无阴影"）。
 * 默认 1.5 描边，viewBox 0 0 16 16，size 可在外部通过 width/height 控制。
 */
defineProps<{
  name: string
  size?: number | string
}>()
</script>

<template>
  <svg
    v-if="name === 'home'"
    :width="size ?? 16" :height="size ?? 16" viewBox="0 0 16 16" aria-hidden="true"
  >
    <path d="M2.5 7.5L8 2.5L13.5 7.5V13a.5.5 0 0 1-.5.5H10V10H6V13.5H3a.5.5 0 0 1-.5-.5z"
          fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
  </svg>

  <svg
    v-else-if="name === 'download'"
    :width="size ?? 16" :height="size ?? 16" viewBox="0 0 16 16" aria-hidden="true"
  >
    <path d="M8 2v8m0 0l-3-3m3 3l3-3" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M2.5 11.5V13a.5.5 0 0 0 .5.5h10a.5.5 0 0 0 .5-.5v-1.5" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
  </svg>

  <svg
    v-else-if="name === 'settings'"
    :width="size ?? 16" :height="size ?? 16" viewBox="0 0 16 16" aria-hidden="true"
  >
    <circle cx="8" cy="8" r="2" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <path d="M13 8a5 5 0 0 0-.1-1l1.3-1-1.3-2.2-1.6.5a5 5 0 0 0-1.7-1L9.3 1.5h-2.6L6.4 3.3a5 5 0 0 0-1.7 1L3.1 3.8L1.8 6l1.3 1A5 5 0 0 0 3 8a5 5 0 0 0 .1 1l-1.3 1l1.3 2.2l1.6-.5a5 5 0 0 0 1.7 1l.3 1.8h2.6l.3-1.8a5 5 0 0 0 1.7-1l1.6.5l1.3-2.2l-1.3-1A5 5 0 0 0 13 8z"
          fill="none" stroke="currentColor" stroke-width="1.1" stroke-linejoin="round"/>
  </svg>

  <svg
    v-else-if="name === 'info'"
    :width="size ?? 16" :height="size ?? 16" viewBox="0 0 16 16" aria-hidden="true"
  >
    <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <line x1="8" y1="7" x2="8" y2="11.5" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
    <circle cx="8" cy="4.8" r="0.6" fill="currentColor"/>
  </svg>

  <svg
    v-else-if="name === 'search'"
    :width="size ?? 16" :height="size ?? 16" viewBox="0 0 16 16" aria-hidden="true"
  >
    <circle cx="7" cy="7" r="4" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <line x1="10" y1="10" x2="13" y2="13" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
  </svg>

  <svg
    v-else-if="name === 'plus'"
    :width="size ?? 16" :height="size ?? 16" viewBox="0 0 16 16" aria-hidden="true"
  >
    <line x1="8" y1="3" x2="8" y2="13" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
    <line x1="3" y1="8" x2="13" y2="8" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
  </svg>

  <svg
    v-else-if="name === 'refresh'"
    :width="size ?? 16" :height="size ?? 16" viewBox="0 0 16 16" aria-hidden="true"
  >
    <path d="M3 8 a5 5 0 0 1 8.5 -3.5 L13 6 M13 3 L13 6 L10 6" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
    <path d="M13 8 a5 5 0 0 1 -8.5 3.5 L3 10 M3 13 L3 10 L6 10" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>

  <svg
    v-else-if="name === 'lock'"
    :width="size ?? 16" :height="size ?? 16" viewBox="0 0 16 16" aria-hidden="true"
  >
    <rect x="3.5" y="7" width="9" height="6" rx="1" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <path d="M5.5 7 V5 a2.5 2.5 0 0 1 5 0 V7" fill="none" stroke="currentColor" stroke-width="1.3"/>
  </svg>

  <svg
    v-else-if="name === 'flag'"
    :width="size ?? 16" :height="size ?? 16" viewBox="0 0 16 16" aria-hidden="true"
  >
    <line x1="3" y1="2" x2="3" y2="14" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
    <path d="M3 3 L12 3 L10 5.5 L12 8 L3 8 Z" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linejoin="round"/>
  </svg>

  <svg
    v-else-if="name === 'wifi-off'"
    :width="size ?? 16" :height="size ?? 16" viewBox="0 0 16 16" aria-hidden="true"
  >
    <line x1="2" y1="2" x2="14" y2="14" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
    <path d="M3 8 a9 9 0 0 1 3 -2.5" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
    <path d="M13 8 a9 9 0 0 0 -3 -2.5" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
    <path d="M5.5 11 a4 4 0 0 1 5 0" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
    <circle cx="8" cy="13" r="0.6" fill="currentColor"/>
  </svg>

  <svg
    v-else-if="name === 'mod'"
    :width="size ?? 16" :height="size ?? 16" viewBox="0 0 16 16" aria-hidden="true"
  >
    <rect x="1.5" y="1.5" width="5" height="5" fill="none" stroke="currentColor" stroke-width="1.2"/>
    <rect x="9.5" y="1.5" width="5" height="5" fill="none" stroke="currentColor" stroke-width="1.2"/>
    <rect x="1.5" y="9.5" width="5" height="5" fill="none" stroke="currentColor" stroke-width="1.2"/>
    <rect x="9.5" y="9.5" width="5" height="5" fill="none" stroke="currentColor" stroke-width="1.2"/>
  </svg>

  <svg
    v-else-if="name === 'map'"
    :width="size ?? 16" :height="size ?? 16" viewBox="0 0 16 16" aria-hidden="true"
  >
    <path d="M1.5 3.5l4-1.5l5 1.5l4-1.5v10l-4 1.5l-5-1.5l-4 1.5z"
          fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
    <line x1="5.5" y1="2" x2="5.5" y2="12" stroke="currentColor" stroke-width="1.2"/>
    <line x1="10.5" y1="3.5" x2="10.5" y2="13.5" stroke="currentColor" stroke-width="1.2"/>
  </svg>

  <svg
    v-else-if="name === 'list'"
    :width="size ?? 16" :height="size ?? 16" viewBox="0 0 16 16" aria-hidden="true"
  >
    <line x1="2" y1="4" x2="14" y2="4" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
    <line x1="2" y1="8" x2="14" y2="8" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
    <line x1="2" y1="12" x2="10" y2="12" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
  </svg>

  <svg
    v-else-if="name === 'plus'"
    :width="size ?? 16" :height="size ?? 16" viewBox="0 0 16 16" aria-hidden="true"
  >
    <line x1="8" y1="3" x2="8" y2="13" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
    <line x1="3" y1="8" x2="13" y2="8" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
  </svg>

  <svg
    v-else-if="name === 'check'"
    :width="size ?? 16" :height="size ?? 16" viewBox="0 0 16 16" aria-hidden="true"
  >
    <path d="M3 8.5L6.5 12L13 4.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
  </svg>

  <svg
    v-else-if="name === 'close'"
    :width="size ?? 16" :height="size ?? 16" viewBox="0 0 16 16" aria-hidden="true"
  >
    <line x1="4" y1="4" x2="12" y2="12" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
    <line x1="12" y1="4" x2="4" y2="12" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
  </svg>

  <svg
    v-else-if="name === 'launch'"
    :width="size ?? 16" :height="size ?? 16" viewBox="0 0 16 16" aria-hidden="true"
  >
    <path d="M5 3v3.5l-2-.5l4 7l1.5-3l3 1.5z" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
  </svg>

  <svg
    v-else-if="name === 'multiplayer'"
    :width="size ?? 16" :height="size ?? 16" viewBox="0 0 16 16" aria-hidden="true"
  >
    <circle cx="5.5" cy="6" r="2" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <circle cx="10.5" cy="6" r="2" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <path d="M2 12.5c.5-1.8 2-3 3.5-3s3 1.2 3.5 3" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
    <path d="M7 12.5c.5-1.8 2-3 3.5-3s3 1.2 3.5 3" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
  </svg>

  <svg
    v-else-if="name === 'network'"
    :width="size ?? 16" :height="size ?? 16" viewBox="0 0 16 16" aria-hidden="true"
  >
    <circle cx="8" cy="3" r="1.6" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <circle cx="3" cy="12" r="1.6" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <circle cx="13" cy="12" r="1.6" fill="none" stroke="currentColor" stroke-width="1.3"/>
    <path d="M7.2 4.4 4.2 10.6M8.8 4.4l3 6.2M4.5 12h7" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
  </svg>
</template>
