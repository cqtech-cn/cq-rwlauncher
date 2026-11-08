<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { windowApi, whenReady } from '@/api/pywebview'
import { setLang } from '@/i18n'
import { festivalActive, festivalId, festivalName, festivalPeriod, festivalIconPath } from '@/stores/festival'

/*
 * 标题栏拖动：
 * pywebview 5.4 + edgechromium 内置拖动：
 *   - 元素加 .pywebview-drag-region class，pywebview 在 customize.js 里
 *     自动监听 mousedown + mousemove，调后端 pywebviewMoveWindow 移动窗口
 *   - 子元素（按钮）加 @mousedown.stop 阻止冒泡，避免被当成 drag start
 *
 * 最大化状态由后端维护（pywebview maximized/restored 事件），
 * 通过 rw:window:maxstate 推送到前端，标题栏据此切换图标。
 */

const maximized = ref(false)

/** 当前语言：zh-CN 显示「中」，en-US 显示「EN」 */
const { locale, t } = useI18n()
const langLabel = computed(() => (locale.value === 'zh-CN' ? '中' : 'EN'))

const toggleLang = () => {
  const next = locale.value === 'zh-CN' ? 'en-US' : 'zh-CN'
  locale.value = setLang(next)
}

const handleMinimize = () => windowApi.minimize()
const handleClose = () => {
  // 触发 App.vue 的关闭逻辑（首次询问 / 走配置）
  window.dispatchEvent(new CustomEvent('rw:titlebar:close'))
}

const toggleMax = () => {
  windowApi.toggleMaximize()
}

/**
 * 最大化状态下禁止标题栏拖动窗口（与正常软件一致）。
 * pywebview 的 JS 拖动不检查窗口状态，这里在捕获阶段拦截
 * mousedown，阻止事件到达 pywebview 的 drag region 监听器。
 */
const onDragMouseDown = (e: MouseEvent) => {
  if (maximized.value) {
    e.preventDefault()
    e.stopPropagation()
  }
}

const onMaxState = (e: Event) => {
  const detail = (e as CustomEvent<{ maximized: boolean }>).detail
  if (detail && typeof detail.maximized === 'boolean') {
    maximized.value = detail.maximized
  }
}

onMounted(async () => {
  window.addEventListener('rw:window:maxstate', onMaxState)
  try {
    await whenReady()
    const st = await windowApi.getWindowState()
    maximized.value = !!st?.maximized
  } catch {
    // 浏览器开发模式下无 API，保持默认
  }
})

onUnmounted(() => {
  window.removeEventListener('rw:window:maxstate', onMaxState)
})
</script>

<template>
  <div class="title-bar pywebview-drag-region">
    <div class="title-bar__drag"
      :title="t('titlebar.dblclick')"
      @mousedown.capture="onDragMouseDown"
      @dblclick="toggleMax"
    >
      <span class="title-bar__title"><strong>CQ</strong><small>RWLauncher</small></span>
      <!-- 节日主题角标：仅在法定假期当天显示 -->
      <span
        v-if="festivalActive"
        class="title-bar__festival"
        :title="festivalPeriod ? `${festivalName} · ${festivalPeriod}` : festivalName"
      >
        <svg viewBox="0 0 16 16" width="11" height="11" aria-hidden="true">
          <path :d="festivalIconPath(festivalId)" fill="none" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" stroke-linejoin="round" />
        </svg>
        <span>{{ festivalName }}</span>
      </span>
    </div>
    <div class="title-bar__btns">
      <button
        class="t-btn t-btn--lang"
        :title="t('titlebar.langLabel')"
        :aria-label="t('titlebar.langLabel')"
        @mousedown.stop
        @click="toggleLang"
      >
        <span class="t-btn__lang">{{ langLabel }}</span>
      </button>
      <button
        class="t-btn"
        :title="maximized ? t('titlebar.restore') : t('titlebar.maximize')"
        :aria-label="maximized ? t('titlebar.restore') : t('titlebar.maximize')"
        @mousedown.stop
        @click="toggleMax"
      >
        <span class="t-btn__icon">
          <svg v-if="!maximized" viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
            <rect x="2" y="2.5" width="8" height="7" fill="none" stroke="currentColor" stroke-width="1" />
          </svg>
          <svg v-else viewBox="0 0 12 12" width="10" height="10" aria-hidden="true">
            <rect x="1.5" y="3" width="7.5" height="6.5" fill="none" stroke="currentColor" stroke-width="1" />
            <path d="M3 3 V1.5 H10.5 V9 H9" fill="none" stroke="currentColor" stroke-width="1" />
          </svg>
        </span>
      </button>
      <button
        class="t-btn t-btn--min"
        :title="t('titlebar.minimize')"
        :aria-label="t('titlebar.minimize')"
        @mousedown.stop
        @click="handleMinimize"
      >
        <span class="t-btn__icon">
          <svg viewBox="0 0 12 12" width="11" height="11" aria-hidden="true">
            <line x1="2" y1="6" x2="10" y2="6" stroke="currentColor" stroke-width="1" stroke-linecap="round" />
          </svg>
        </span>
      </button>
      <button
        class="t-btn t-btn--close"
        :title="t('titlebar.close')"
        :aria-label="t('titlebar.close')"
        @mousedown.stop
        @click="handleClose"
      >
        <span class="t-btn__icon">
          <svg viewBox="0 0 12 12" width="11" height="11" aria-hidden="true">
            <line x1="2" y1="2" x2="10" y2="10" stroke="currentColor" stroke-width="1" stroke-linecap="round" />
            <line x1="10" y1="2" x2="2" y2="10" stroke="currentColor" stroke-width="1" stroke-linecap="round" />
          </svg>
        </span>
      </button>
    </div>
  </div>
</template>

<style scoped>
/* 标题栏：半模态玻璃（渐变边缘 + 羽化），压在主内容之上 */
.title-bar {
  position: relative;
  height: 34px;
  display: flex;
  align-items: stretch;
  background: var(--glass-bg);
  backdrop-filter: blur(var(--glass-blur)) saturate(130%);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(130%);
  box-shadow: var(--glass-feather),
    0 1px 8px -5px color-mix(in srgb, var(--text) 45%, transparent);
  user-select: none;
  flex-shrink: 0;
  z-index: 20;
  /* 拖动由 .pywebview-drag-region class 触发 */
}

/* 底边渐变分隔线：两端羽化，避免生硬横切 */
.title-bar::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 1px;
  background: linear-gradient(
    90deg,
    transparent,
    var(--border) 16%,
    var(--border) 84%,
    transparent
  );
  pointer-events: none;
}

.title-bar__drag {
  flex: 1;
  display: flex;
  align-items: center;
  padding-left: 12px;
  min-width: 0;
  cursor: default;
}

.title-bar__title {
  font-size: 12px;
  font-weight: 500;
  color: var(--text);
  letter-spacing: 0.4px;
  display: flex;
  align-items: baseline;
  gap: 2px;
}
.title-bar__title strong {
  font-weight: 700;
  font-size: 13px;
}
.title-bar__title small {
  font-size: 10px;
  font-weight: 400;
  color: var(--text-3);
  letter-spacing: 0.6px;
}

/* 节日角标：点缀色小胶囊 */
.title-bar__festival {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 10px;
  padding: 1px 8px;
  border: 1px solid color-mix(in srgb, var(--accent) 55%, transparent);
  border-radius: var(--r-full);
  background: var(--festival-tint, transparent);
  color: var(--accent);
  font-size: 10.5px;
  font-weight: 600;
  letter-spacing: 0.4px;
  flex-shrink: 0;
}
.title-bar__festival svg {
  display: block;
  color: var(--festival-deco, currentColor);
}

.title-bar__btns {
  display: flex;
  align-items: stretch;
}

/*
 * 标题栏按钮
 * - hover / active 用过渡令牌平滑切换
 * - active 时图标轻微"按下"，模拟物理反馈
 * - 关闭按钮 hover 变红（行业惯例）
 */
.t-btn {
  position: relative;
  width: 46px;
  height: 34px;
  background: transparent;
  border: none;
  color: var(--text);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 0;
  cursor: pointer;
  outline: none;
  overflow: hidden;
  transition: background-color var(--dur-1) var(--ease), color var(--dur-1) var(--ease);
}

.t-btn::before {
  content: "";
  position: absolute;
  inset: 0;
  background: currentColor;
  opacity: 0;
  transition: opacity var(--dur-1) var(--ease);
  pointer-events: none;
}

.t-btn__icon {
  position: relative;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  transition: transform var(--dur-1) var(--ease);
}

/* 语言切换按钮：紧凑文本，窄宽度 */
.t-btn--lang {
  width: 36px;
  border-right: 1px solid var(--border);
}
.t-btn__lang {
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.5px;
  color: var(--text-2);
  transition: color var(--dur-1) var(--ease);
}
.t-btn--lang:hover .t-btn__lang {
  color: var(--accent);
}

.t-btn:hover {
  background: var(--hover-tint);
}

.t-btn:active {
  background: var(--press-tint);
}
.t-btn:active .t-btn__icon {
  transform: scale(0.86);
}

/* 关闭按钮：hover 变红，icon 反白 */
.t-btn--close {
  transition: background-color var(--dur-2) var(--ease), color var(--dur-2) var(--ease);
}
.t-btn--close:hover {
  background: #c83a3a;
  color: #ffffff;
}
.t-btn--close:active {
  background: #a82c2c;
}
.t-btn--close:hover .t-btn__icon,
.t-btn--close:active .t-btn__icon {
  color: #ffffff;
}
</style>
