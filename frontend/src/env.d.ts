/// <reference types="vite/client" />

declare module '*.vue' {
  import type { DefineComponent } from 'vue'
  const component: DefineComponent<{}, {}, any>
  export default component
}

declare module '*.svg' {
  const src: string
  export default src
}

declare module '*.png' {
  const src: string
  export default src
}

declare module '*.jpg' {
  const src: string
  export default src
}

declare module '*.jpeg' {
  const src: string
  export default src
}

declare module '*.webp' {
  const src: string
  export default src
}

// pywebview 注入的全局对象
declare global {
  interface Window {
    pywebview?: {
      api: any
    }
    __rw?: {
      onCloseAttempt: () => void | Promise<void>
    }
  }

  // vite.config.ts define 注入：前端构建时刻（如 "2026/8/21 14:30:00"）
  const __BUILD_DATE__: string
}

export {}
