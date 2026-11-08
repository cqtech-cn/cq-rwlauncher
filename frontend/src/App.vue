<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import TitleBar from '@/components/TitleBar.vue'
import SplashScreen from '@/components/SplashScreen.vue'
import FirstCloseDialog from '@/components/FirstCloseDialog.vue'
import SteamTutorialDialog from '@/components/SteamTutorialDialog.vue'
import HomeView from '@/views/HomeView.vue'
import AccountView from '@/views/AccountView.vue'
import DownloadView from '@/views/DownloadView.vue'
import RoomView from '@/views/RoomView.vue'
import SettingsView from '@/views/SettingsView.vue'
import AboutView from '@/views/AboutView.vue'
import TutorialView from '@/views/TutorialView.vue'
import ServiceStatusView from '@/views/ServiceStatusView.vue'
import Icon from '@/components/Icon.vue'
import { configApi, windowApi, resourceApi, updateApi, whenReady } from '@/api/pywebview'
import { useToastStore } from '@/stores/toast'
import { applyAppearance, sanitizeAppearance, setBackground } from '@/stores/appearance'
import { loadFestivalTheme } from '@/stores/festival'
import {
  accountBaseUrl,
  accountLastError,
  accountProbing,
  dismissAccountAlert,
  probeAccount,
  showAccountAlert,
  startAccountWatch,
  stopAccountWatch,
} from '@/stores/serviceStatus'
import { on, RW_EVENTS, type BlockedEvent, type StatusEvent } from '@/api/events'
import { ElMessageBox } from 'element-plus'

const toast = useToastStore()
const { t } = useI18n()

type TabId = 'home' | 'account' | 'download' | 'room' | 'settings' | 'status' | 'tutorial' | 'about'
const currentTab = ref<TabId>('home')

const tabs: { id: TabId; icon: string }[] = [
  { id: 'home', icon: 'home' },
  { id: 'account', icon: 'lock' },
  { id: 'download', icon: 'download' },
  { id: 'room', icon: 'multiplayer' },
  { id: 'settings', icon: 'settings' },
  { id: 'status', icon: 'network' },
  { id: 'tutorial', icon: 'list' },
  { id: 'about', icon: 'info' },
]

const firstCloseDialogVisible = ref(false)
const steamTutorialVisible = ref(false)

/* —— 从其他页面跳转到教程 tab —— */
const onOpenTutorial = () => {
  currentTab.value = 'tutorial'
}

/* —— Steam 版接入教程 —— */
const onShowSteamTutorial = () => {
  steamTutorialVisible.value = true
}

/* —— 启动动效 —— */
const showSplash = ref(true)

const onSplashDone = () => {
  showSplash.value = false
}

/**
 * 统一的"关闭启动器"入口。
 *  - 来自 TitleBar 的 X 按钮
 *  - 来自 OS 原生关闭（Alt+F4 / 任务栏右键关闭），main.py 转发到 window.__rw.onCloseAttempt
 */
const onCloseAttempt = async () => {
  let behavior: string | null = null
  try {
    behavior = await configApi.getCloseBehavior()
  } catch {
    // 浏览器开发模式下没有 API，按 exit 处理
    behavior = 'exit'
  }

  if (behavior === 'minimize') {
    try { await windowApi.minimize() } catch {}
  } else if (behavior === 'exit') {
    try { await windowApi.close() } catch {}
  } else {
    // behavior === 'ask'：弹窗询问
    firstCloseDialogVisible.value = true
  }
}

const onFirstCloseResolved = async (behavior: 'minimize' | 'exit') => {
  if (behavior === 'minimize') {
    try { await windowApi.minimize() } catch {}
  } else {
    try { await windowApi.close() } catch {}
  }
}

const onTitlebarClose = () => onCloseAttempt()

/** 账号服务不可用提示条：跳到「设置 → 账号」修改服务地址 */
const onAlertToSettings = () => {
  currentTab.value = 'settings'
  window.dispatchEvent(new CustomEvent('rw:open:settings-section', { detail: 'account' }))
}

/** 提示条：重新检测账号服务 */
const onAlertRetry = () => {
  void probeAccount()
}

onMounted(async () => {
  // 暴露给 main.py 通过 evaluate_js 调用的钩子
  window.__rw = {
    onCloseAttempt: () => { onCloseAttempt() },
  }
  window.addEventListener('rw:titlebar:close', onTitlebarClose)
  window.addEventListener('rw:show:steam-tutorial', onShowSteamTutorial)
  window.addEventListener('rw:open:tutorial', onOpenTutorial)

  // 资源格式被拒绝时弹窗提示（后端 rw:blocked 事件）
  offBlocked = on<BlockedEvent>(RW_EVENTS.BLOCKED, (d) => {
    ElMessageBox.alert(d.message || t('app.blocked.msg'), t('app.blocked.title'), {
      confirmButtonText: t('app.blocked.gotIt'),
      showClose: false,
    }).catch(() => {})
  })

  // 模组包嵌套检测：询问用户是否自动展平修复（fix 修复 / keep 保持原样）
  offConfirm = on<StatusEvent>(RW_EVENTS.STATUS, (d) => {
    if (d.status !== 'needs_confirm') return
    const name = d.title || d.folder || t('app.modNest.defaultName')
    ElMessageBox.confirm(
      t('app.modNest.msg', { name, top: d.top || '…' }),
      t('app.modNest.title'),
      {
        confirmButtonText: t('app.modNest.fix'),
        cancelButtonText: t('app.modNest.keep'),
        type: 'warning',
      },
    )
      .then(() => {
        resourceApi.confirm(d.task_id, 'fix').catch(() => {})
      })
      .catch(() => {
        resourceApi.confirm(d.task_id, 'keep').catch(() => {})
      })
  })

  // 等待 pywebview ready 后加载并应用外观配置
  await whenReady()
  try {
    const cfg = await configApi.get()
    if (cfg?.appearance) {
      applyAppearance(sanitizeAppearance(cfg.appearance))
      // 背景图用 base64 data URI 渲染（localhost HTTP 页面无法加载 file://）
      const bgPath = (cfg.appearance as any)?.background_image
      if (bgPath) {
        const r = await windowApi.backgroundImageData()
        if (r?.ok && r.data) {
          setBackground(bgPath, r.data)
        }
      }
    }
  } catch {
    // 浏览器开发模式：保持默认外观
  }

  // 账号服务可用性探测（提示条显示用），并开启 60 秒静默复查
  void probeAccount()
  startAccountWatch()

  // 节日特别主题：命中法定假期时自动切换点缀配色
  void loadFestivalTheme()

  // 检查更新：有新版本弹窗提示（公告拉取失败时静默，不打扰用户）
  try {
    const upd = await updateApi.check()
    if (upd?.has_update) {
      await ElMessageBox.alert(
        upd.info || '',
        t('app.update.title', { v: upd.latest_version || '' }),
        {
          confirmButtonText: t('app.update.gotIt'),
          showClose: false,
          customStyle: {
            whiteSpace: 'pre-line',
            maxHeight: '70vh',
            overflowY: 'auto',
          },
        },
      ).catch(() => {})
    }
  } catch {
    // 浏览器开发模式或无 API：忽略
  }
})

let offBlocked: (() => void) | null = null
let offConfirm: (() => void) | null = null

onUnmounted(() => {
  window.removeEventListener('rw:titlebar:close', onTitlebarClose)
  window.removeEventListener('rw:show:steam-tutorial', onShowSteamTutorial)
  window.removeEventListener('rw:open:tutorial', onOpenTutorial)
  offBlocked?.()
  offConfirm?.()
  stopAccountWatch()
})
</script>

<template>
  <!-- 启动动效 -->
  <SplashScreen
    :visible="showSplash"
    @done="onSplashDone"
  />

  <div v-show="!showSplash" class="app">
    <TitleBar />

    <nav class="tabs">
      <div class="tabs__center">
        <button
          v-for="tab in tabs"
          :key="tab.id"
          :class="['tabs__item', { 'tabs__item--active': currentTab === tab.id }]"
          @click="currentTab = tab.id"
        >
          <Icon :name="tab.icon" :size="14" />
          <span>{{ t(`app.tabs.${tab.id}`) }}</span>
        </button>
      </div>
    </nav>

    <!-- 账号服务不可用：醒目横幅（只影响平台渠道，铁锈盒子渠道照常可用） -->
    <div v-if="showAccountAlert" class="svc-alert">
      <span class="svc-alert__icon" aria-hidden="true">
        <svg viewBox="0 0 16 16" width="16" height="16">
          <path d="M8 1.6 15.2 14H0.8L8 1.6Z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>
          <path d="M8 6.2v3.6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
          <circle cx="8" cy="12" r="0.85" fill="currentColor"/>
        </svg>
      </span>
      <div class="svc-alert__body">
        <div class="svc-alert__title">{{ t('app.accountAlert.title') }}</div>
        <div class="svc-alert__msg">
          {{ t('app.accountAlert.msg', { url: accountBaseUrl || '—' }) }}
          <span v-if="accountLastError" class="svc-alert__reason">
            {{ t('app.accountAlert.reason', { reason: accountLastError }) }}
          </span>
        </div>
      </div>
      <div class="svc-alert__actions">
        <button class="svc-alert__btn" @click="onAlertToSettings">
          {{ t('app.accountAlert.toSettings') }}
        </button>
        <button class="svc-alert__btn" :disabled="accountProbing" @click="onAlertRetry">
          {{ accountProbing ? t('app.accountAlert.checking') : t('app.accountAlert.retry') }}
        </button>
        <button class="svc-alert__btn svc-alert__btn--ghost" @click="dismissAccountAlert()">
          {{ t('app.accountAlert.dismiss') }}
        </button>
      </div>
    </div>

    <main class="app__main">
      <HomeView v-show="currentTab === 'home'" />
      <AccountView v-show="currentTab === 'account'" />
      <DownloadView v-show="currentTab === 'download'" />
      <RoomView v-show="currentTab === 'room'" />
      <SettingsView v-show="currentTab === 'settings'" />
      <ServiceStatusView v-show="currentTab === 'status'" />
      <TutorialView v-show="currentTab === 'tutorial'" />
      <AboutView v-show="currentTab === 'about'" />
    </main>

    <FirstCloseDialog
      v-model:visible="firstCloseDialogVisible"
      @resolved="onFirstCloseResolved"
    />

    <SteamTutorialDialog v-model:visible="steamTutorialVisible" />

    <!-- Toast 容器 -->
    <div class="toast-stack">
      <div
        v-for="t in toast.toasts.value"
        :key="t.id"
        :class="['toast', `toast--${t.kind}`]"
        @click="toast.dismiss(t.id)"
      >
        {{ t.message }}
      </div>
    </div>
  </div>
</template>

<style scoped>
.app {
  display: flex;
  flex-direction: column;
  height: 100%;
  background: transparent;
}

/* 居中导航栏：胶囊分段式，底部保留细线（节日主题会点亮该线） */
.tabs {
  display: flex;
  justify-content: center;
  border-bottom: 1px solid var(--border);
  background: var(--panel-solid);
  flex-shrink: 0;
  padding: 6px 12px;
  transition: border-color var(--dur-3) var(--ease);
}
.tabs__center {
  display: flex;
  gap: 4px;
}

.tabs__item {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--r-full);
  padding: 6px 15px;
  font-size: 13px;
  color: var(--text-3);
  cursor: pointer;
  outline: none;
  transition: background-color var(--dur-2) var(--ease), color var(--dur-2) var(--ease),
    border-color var(--dur-2) var(--ease);
}
.tabs__item:hover {
  color: var(--text);
  background: var(--hover-tint);
}
.tabs__item--active {
  color: var(--text);
  font-weight: 600;
  background: var(--selected-tint);
  border-color: color-mix(in srgb, var(--accent) 36%, transparent);
}
.tabs__item:active {
  background: var(--press-tint);
}
.tabs__item svg {
  display: block;
}

.app__main {
  flex: 1;
  min-height: 0;
  display: flex;
  background: transparent;
}

/* 账号服务不可用横幅：语义底色 + 玻璃 + 左侧强调条，保证在任何主题下都醒目 */
.svc-alert {
  display: flex;
  align-items: center;
  gap: 12px;
  flex-shrink: 0;
  margin: 8px 12px 0;
  padding: 11px 14px 11px 12px;
  background: color-mix(in srgb, var(--danger-bg) 78%, var(--panel));
  color: var(--danger-text);
  border: 1px solid color-mix(in srgb, var(--danger-text) 34%, transparent);
  border-left: 4px solid var(--danger-text);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-1);
  animation: svc-alert-in var(--dur-3) var(--ease-out);
}
@keyframes svc-alert-in {
  from { opacity: 0; transform: translateY(-6px); }
  to { opacity: 1; transform: translateY(0); }
}
.svc-alert__icon {
  display: inline-flex;
  flex-shrink: 0;
}
.svc-alert__body {
  flex: 1;
  min-width: 0;
}
.svc-alert__title {
  font-size: 13px;
  font-weight: 700;
  letter-spacing: 0.3px;
}
.svc-alert__msg {
  margin-top: 2px;
  font-size: 12px;
  line-height: 1.6;
}
.svc-alert__reason {
  margin-left: 6px;
  opacity: 0.85;
}
.svc-alert__actions {
  display: flex;
  gap: 8px;
  flex-shrink: 0;
}
.svc-alert__btn {
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 600;
  border-radius: var(--r-full);
  background: transparent;
  color: inherit;
  border: 1px solid currentColor;
  transition: background-color var(--dur-1) var(--ease);
}
.svc-alert__btn:hover:not(:disabled) {
  background: color-mix(in srgb, currentColor 14%, transparent);
}
.svc-alert__btn:disabled {
  opacity: 0.55;
  cursor: default;
}
.svc-alert__btn--ghost {
  border-color: transparent;
  opacity: 0.8;
}
.svc-alert__btn--ghost:hover {
  border-color: currentColor;
  opacity: 1;
}

.app__main > * {
  flex: 1;
  min-width: 0;
}

/* 自绘 Toast */
.toast-stack {
  position: fixed;
  bottom: 20px;
  right: 20px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  z-index: 9999;
  pointer-events: none;
}

.toast {
  padding: 10px 16px;
  font-size: 12px;
  color: var(--text);
  background: var(--glass-bg);
  backdrop-filter: blur(var(--glass-blur)) saturate(130%);
  -webkit-backdrop-filter: blur(var(--glass-blur)) saturate(130%);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-2);
  min-width: 180px;
  max-width: 360px;
  pointer-events: auto;
  cursor: pointer;
  animation: toast-in var(--dur-3) var(--ease-out);
  transition: transform var(--dur-2) var(--ease), opacity var(--dur-2) var(--ease);
}
.toast:hover {
  transform: translateY(-1px);
}
@keyframes toast-in {
  from { opacity: 0; transform: translateX(14px); }
  to { opacity: 1; transform: translateX(0); }
}

.toast--success { background: var(--success-bg); border-color: transparent; color: var(--success-text); }
.toast--error   { background: var(--danger-bg);  border-color: transparent; color: var(--danger-text); }
.toast--warning { background: var(--warn-bg);    border-color: transparent; color: var(--warn-text); }
.toast--info    { background: var(--info-bg);    border-color: transparent; color: var(--info-text); }
</style>
