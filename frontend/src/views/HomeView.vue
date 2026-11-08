<script setup lang="ts">
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage } from 'element-plus'
import { gameApi, configApi, whenReady } from '@/api/pywebview'
import { on, RW_EVENTS, type StatusEvent } from '@/api/events'
import { useDownloadsStore, fmt } from '@/stores/downloads'
import { useToastStore } from '@/stores/toast'
import { appearance } from '@/stores/appearance'
import qqUrl from '@/assets/qq-group.jpg'
import VersionSelector from '@/components/VersionSelector.vue'

const { t } = useI18n()
const toast = useToastStore()
const dlStore = useDownloadsStore()

const installed = ref(false)
const gamePath = ref('')
const gameDir = ref('')
const lastArgs = ref('')
const gameRunning = ref(false)
const installTaskId = 'game_install'

/** 窄屏（宽屏时版本列表常驻右栏，窄屏时收进抽屉） */
const narrow = ref(false)
const drawerOpen = ref(false)

const installState = computed(() => dlStore.get(installTaskId))

const installPct = computed(() => {
  const s = installState.value
  if (!s || s.total <= 0) return 0
  return Math.min(100, Math.round((s.downloaded / s.total) * 100))
})

const installStatus = computed(() => installState.value?.status ?? 'idle')

const hasTotal = computed(() => {
  const s = installState.value
  return !!s && s.total > 0
})

const downloadedText = computed(() => {
  const s = installState.value
  if (!s) return ''
  const dl = fmt.bytes(s.downloaded || 0)
  if (hasTotal.value) {
    return `${dl} / ${fmt.bytes(s.total)}`
  }
  const sp = s.speed && s.speed > 0 ? ` · ${fmt.speed(s.speed)}` : ''
  return `${dl}${sp}`
})

const downloading = computed(
  () => installStatus.value === 'downloading' || installStatus.value === 'extracting',
)

const refresh = async () => {
  const s = await gameApi.status()
  // Java 版（简体中文增强版）游戏目录只有 jar 没有 exe：exists=false 但 launchable=true
  installed.value = s.launchable || s.exists
  gamePath.value = s.exists ? s.path : s.java_jar || ''
  gameDir.value = s.game_root || s.game_dir
  const cfg = await configApi.get()
  lastArgs.value = cfg.last_launch_args || ''
}

const onInstall = async () => {
  try {
    const tid = await gameApi.install()
    dlStore.add(tid)
    toast.push(t('home.installStarted'), 'info')
  } catch (e: any) {
    ElMessage.error(t('home.installSubmitFailed', { err: e?.message || t('common.unknownError') }))
  }
}

const onLaunch = async () => {
  if (!installed.value) {
    ElMessage.warning(t('home.launchFirst'))
    return
  }
  try {
    const res = await gameApi.launch(lastArgs.value)
    if (!res.ok) {
      if (res.needs_jre) {
        // Java 版（简体中文增强版）缺 JRE：自动下载中提示，未开启自动下载给 warning
        if (res.jre_downloading) {
          ElMessage.info(res.error || t('home.javaJreInstalling'))
        } else {
          ElMessage.warning(res.error || t('home.javaJreMissing'))
        }
      } else {
        ElMessage.error(res.error || t('home.launchFailed'))
      }
      return
    }
    toast.push(t('home.gameLaunched'), 'success')
    await configApi.update({ last_launch_args: lastArgs.value })
  } catch (e: any) {
    ElMessage.error(t('home.launchFailedErr', { err: e?.message || t('common.unknownError') }))
  }
}

const onChoosePath = () => {
  ElMessage.info(t('home.choosePathHint'))
}

const onOpenGameDir = () => {
  const target = gamePath.value
    ? gamePath.value.replace(/[\\/][^\\/]+$/, '')
    : gameDir.value
  if (!target) {
    ElMessage.warning(t('home.dirUndetermined'))
    return
  }
  try {
    navigator.clipboard?.writeText(target)
    toast.push(t('home.dirCopied', { dir: target }), 'info')
  } catch {
    ElMessage.info(t('home.gameDir', { dir: target }))
  }
}

/** 结束游戏进程 */
const onKillGame = async () => {
  try {
    const res = await gameApi.killGame()
    if (res?.ok && res.killed) {
      gameRunning.value = false
      if (res.warning) {
        ElMessage.warning(res.warning)
      } else {
        toast.push(t('home.gameKilled'), 'success')
      }
    } else if (res?.ok) {
      ElMessage.info(t('home.noGameProcess'))
    } else {
      ElMessage.error(res?.error || t('home.killFailed'))
    }
  } catch {
    ElMessage.error(t('home.killFailed'))
  }
}

/** 轮询检测游戏进程运行状态（3 秒超时保护，避免后端 tasklist 变慢时请求堆积） */
let runningTimer: number | null = null
const checkRunning = async () => {
  try {
    const r = await Promise.race([
      gameApi.gameRunning(),
      new Promise<null>((resolve) => setTimeout(() => resolve(null), 3000)),
    ])
    if (r) gameRunning.value = !!r.running
  } catch {
    gameRunning.value = false
  }
}

let unsub: (() => void) | null = null
const onStatus = (d: StatusEvent) => {
  if (d.task_id !== installTaskId) return
  if (d.status === 'completed') {
    installed.value = true
    refresh()
    toast.push(t('home.installCompleted'), 'success')
  } else if (d.status === 'failed') {
    ElMessage.error(t('home.installFailed', { err: d.error || t('common.unknownError') }))
  }
}

/** 窄屏断点监听：切回宽屏时顺带收起抽屉 */
const mq = ref<MediaQueryList | null>(null)
const onNarrowChange = (e: MediaQueryListEvent) => {
  narrow.value = e.matches
  if (!e.matches) drawerOpen.value = false
}

onMounted(async () => {
  await whenReady()
  await refresh()
  unsub = on(RW_EVENTS.STATUS, onStatus)
  await checkRunning()
  runningTimer = window.setInterval(checkRunning, 5000)

  mq.value = window.matchMedia('(max-width: 960px)')
  narrow.value = mq.value.matches
  mq.value.addEventListener('change', onNarrowChange)

  if (!installed.value) {
    const state = dlStore.get(installTaskId)
    const status = state?.status
    const idle = !status || status === 'failed' || status === 'canceled' || status === 'completed'
    if (idle) {
      setTimeout(() => {
        if (!installed.value) {
          const task = dlStore.get(installTaskId)
          if (!task || task.status === 'failed' || task.status === 'canceled' || task.status === 'completed') {
            void onInstall()
          }
        }
      }, 400)
    }
  }
})

onUnmounted(() => {
  if (unsub) unsub()
  if (runningTimer !== null) {
    clearInterval(runningTimer)
    runningTimer = null
  }
  mq.value?.removeEventListener('change', onNarrowChange)
})
</script>

<template>
  <div class="home">
    <div class="home__layout">
      <div class="home__main">
        <!-- 主区域：启动游戏（突出显示） -->
        <section v-show="appearance.home_modules.launch" class="home__launch">
          <header class="home__launch-header">
            <div class="home__launch-title-area">
              <h2 class="home__heading">{{ t('home.launch') }}</h2>
              <p class="home__heading-desc">{{ t('home.launchDesc') }}</p>
            </div>
            <div class="home__header-actions">
              <button
                v-if="narrow"
                class="home__version-btn"
                type="button"
                @click="drawerOpen = true"
              >
                <svg class="home__version-icon" viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
                  <path d="M2.5 4.5h11M2.5 8h11M2.5 11.5h7" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
                </svg>
                <span>{{ t('home.versionSelect') }}</span>
              </button>
              <div :class="['home__badge', installed ? 'home__badge--ok' : 'home__badge--off']">
                <span class="home__badge-dot" />
                <span>{{ installed ? t('home.ready') : t('home.notInstalled') }}</span>
              </div>
            </div>
          </header>

          <!-- 启动参数 -->
          <div class="home__field">
            <label class="home__field-label">{{ t('home.argsLabel') }}</label>
            <el-input
              v-model="lastArgs"
              :disabled="!installed"
              :placeholder="t('home.argsPlaceholder')"
              clearable
              size="large"
            />
          </div>

          <!-- 游戏路径 -->
          <div class="home__field">
            <label class="home__field-label">{{ t('home.exeLabel') }}</label>
            <div class="home__path-row">
              <span class="home__path-text">{{ gamePath || t('home.notDetected') }}</span>
              <el-button
                v-if="installed"
                size="small"
                link
                @click="onOpenGameDir"
              >{{ t('home.copyDir') }}</el-button>
            </div>
          </div>

          <!-- 启动 / 结束游戏按钮 -->
          <div class="home__action">
            <button
              class="home__kill-btn"
              :class="{ 'home__kill-btn--off': !gameRunning }"
              :disabled="!installed || !gameRunning"
              @click="onKillGame"
            >
              <svg class="home__kill-icon" viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
                <rect x="2.5" y="2.5" width="11" height="11" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
                <line x1="5" y1="8" x2="11" y2="8" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
              </svg>
              <span>{{ gameRunning ? t('home.killGame') : t('home.gameNotRunning') }}</span>
            </button>
            <button
              :class="['home__launch-btn', { 'home__launch-btn--disabled': !installed }]"
              :disabled="!installed"
              @click="onLaunch"
            >
              <svg class="home__launch-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
                <path d="M5 3v3.5l-2-.5l4 7l1.5-3l3 1.5z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
              </svg>
              <span>{{ installed ? t('home.launchBtn') : t('home.downloadFirst') }}</span>
            </button>
          </div>
        </section>

        <!-- 下载区域（次要信息） -->
        <section v-show="appearance.home_modules.download" class="home__download">
          <header class="home__dl-header">
            <h3 class="home__subheading">{{ t('home.gameDownload') }}</h3>
            <span v-if="installed" class="home__dl-hint">{{ t('home.installedHint') }}</span>
          </header>

          <!-- 免责声明：仅试玩，24 小时内删除 -->
          <div class="home__disclaimer">
            <svg class="home__disclaimer-icon" viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
              <path d="M8 1.5L15 14H1z" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
              <line x1="8" y1="6" x2="8" y2="9.5" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
              <circle cx="8" cy="12" r="0.9" fill="currentColor"/>
            </svg>
            <span>{{ t('home.disclaimer') }}</span>
          </div>

          <div class="home__dl-meta">
            <div class="home__dl-meta-item">
              <span class="home__meta-label">{{ t('home.installDir') }}</span>
              <span class="home__meta-value">{{ gameDir }}</span>
            </div>
          </div>

          <!-- 进度 -->
          <div v-if="downloading" class="home__progress">
            <el-progress
              :percentage="installStatus === 'extracting' ? 100 : (hasTotal ? installPct : 0)"
              :indeterminate="installStatus === 'downloading' && !hasTotal"
              :stroke-width="6"
              :status="installStatus === 'extracting' ? 'success' : undefined"
            />
            <div class="home__progress-text">
              <span v-if="installStatus === 'extracting'">{{ t('home.extracting') }}</span>
              <span v-else>{{ t('home.downloaded', { text: downloadedText }) }}</span>
            </div>
          </div>

          <!-- 操作 -->
          <div class="home__dl-actions">
            <el-button
              :type="installed ? 'default' : 'primary'"
              :loading="downloading"
              :disabled="downloading"
              @click="onInstall"
            >
              {{
                downloading
                  ? (installStatus === 'extracting' ? t('home.extractingBtn') : t('home.downloadingBtn'))
                  : (installed ? t('home.redownload') : t('home.startDownload'))
              }}
            </el-button>
            <el-button
              v-if="!installed"
              size="small"
              link
              @click="onChoosePath"
            >{{ t('home.changePath') }}</el-button>
          </div>
        </section>

        <!-- 官方QQ群宣传（底部） -->
        <section v-show="appearance.home_modules.download" class="home__qq">
          <img
            class="home__qq-img"
            :src="qqUrl"
            :alt="t('about.qqAlt')"
            draggable="false"
          />
          <div class="home__qq-text">
            <div class="home__qq-title">{{ t('home.joinQQ') }}</div>
            <div>{{ t('home.qqDesc') }}</div>
          </div>
        </section>
      </div>

      <!-- 右侧常驻版本栏（窄屏时改用下方抽屉） -->
      <aside v-if="!narrow" class="home__side">
        <VersionSelector :launch-args="lastArgs" @changed="refresh" />
      </aside>
    </div>

    <!-- 窄屏版本抽屉 -->
    <el-drawer
      v-if="narrow"
      v-model="drawerOpen"
      direction="rtl"
      size="360px"
      :append-to-body="true"
      :with-header="false"
    >
      <div class="home__drawer-inner">
        <VersionSelector :launch-args="lastArgs" @changed="refresh" />
      </div>
    </el-drawer>
  </div>
</template>

<style scoped>
/* 页面容器：外层负责滚动，内层负责「主内容 + 右栏」两列布局 */
.home {
  height: 100%;
  overflow-y: auto;
  padding: var(--sp-6) var(--sp-8);
}

.home__layout {
  display: flex;
  align-items: flex-start;
  justify-content: center;
  gap: var(--sp-5);
  width: 100%;
}

.home__main {
  flex: 1 1 auto;
  min-width: 0;
  max-width: 640px;
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
}

/* 右栏：常驻版本列表，页面滚动时跟随吸附 */
.home__side {
  width: 340px;
  flex-shrink: 0;
  position: sticky;
  top: var(--sp-2);
  align-self: flex-start;
  max-height: calc(100vh - 34px - var(--sp-5));
  overflow-y: auto;
}

.home__drawer-inner {
  padding-bottom: var(--sp-2);
}

/* 启动区：页面主视觉，用卡片承载 */
.home__launch {
  background: var(--panel-solid);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-1);
  padding: var(--sp-6) var(--sp-8);
  display: flex;
  flex-direction: column;
  gap: var(--sp-5);
}

.home__launch-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sp-3);
}

.home__launch-title-area {
  flex: 1;
  min-width: 0;
}

.home__header-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-shrink: 0;
}

/* 窄屏「选择版本」按钮：描边风格，与状态标签并排 */
.home__version-btn {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 5px 10px;
  font-size: 11px;
  font-weight: 500;
  color: var(--text-2);
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  cursor: pointer;
  transition: color var(--dur-1) var(--ease), border-color var(--dur-1) var(--ease),
    background-color var(--dur-1) var(--ease);
}

.home__version-btn:hover {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 45%, transparent);
  background: var(--hover-tint);
}

.home__version-icon {
  display: block;
}

.home__heading {
  font-size: 18px;
  font-weight: 700;
  color: var(--text);
  margin: 0 0 3px;
  line-height: 1.3;
}

.home__heading-desc {
  font-size: 11px;
  color: var(--text-3);
  margin: 0;
}

/* 状态标签：胶囊形态，安装状态一眼可辨 */
.home__badge {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  padding: 3px 10px;
  font-size: 11px;
  font-weight: 600;
  letter-spacing: 0.3px;
  border-radius: var(--r-full);
  flex-shrink: 0;
}
.home__badge--ok {
  background: var(--accent);
  color: var(--on-accent);
}
.home__badge--off {
  background: var(--border-soft);
  color: var(--text-4);
}
.home__badge-dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  display: inline-block;
  background: currentColor;
}

.home__field {
  display: flex;
  flex-direction: column;
  gap: 5px;
}
.home__field-label {
  font-size: 11px;
  font-weight: 500;
  color: var(--text-3);
  letter-spacing: 0.2px;
}

.home__path-row {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.home__path-text {
  font-family: "Cascadia Code", "Consolas", "Menlo", monospace;
  font-size: 11px;
  color: var(--text-2);
  word-break: break-all;
  flex: 1;
  min-width: 0;
  line-height: 1.6;
}

/* 启动 / 结束按钮（自绘，更突出） */
.home__action {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  justify-content: flex-end;
  margin-top: 2px;
}

/* 结束游戏按钮：描边风格，运行时可点，hover 变红 */
.home__kill-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 10px 16px;
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  color: var(--text-3);
  font-size: 12px;
  cursor: pointer;
  transition: border-color var(--dur-1) var(--ease), color var(--dur-1) var(--ease),
    background-color var(--dur-1) var(--ease);
}
.home__kill-btn:hover:not(:disabled) {
  border-color: var(--danger-text);
  color: var(--danger-text);
  background: color-mix(in srgb, var(--danger-text) 8%, transparent);
}
.home__kill-btn:active:not(:disabled) {
  background: color-mix(in srgb, var(--danger-text) 16%, transparent);
}
.home__kill-btn:disabled {
  color: var(--accent-disabled);
  border-color: var(--border-soft);
  cursor: not-allowed;
}
.home__kill-icon {
  display: block;
}
.home__launch-btn {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 10px 32px;
  background: var(--accent);
  color: var(--on-accent);
  border: none;
  border-radius: var(--r-sm);
  font-size: 14px;
  font-weight: 600;
  letter-spacing: 0.4px;
  cursor: pointer;
  transition: background-color var(--dur-1) var(--ease), box-shadow var(--dur-2) var(--ease);
}
.home__launch-btn:hover:not(.home__launch-btn--disabled) {
  background: var(--accent-hover);
  box-shadow: var(--shadow-2);
}
.home__launch-btn:active:not(.home__launch-btn--disabled) {
  background: var(--accent-active);
  box-shadow: var(--shadow-1);
}
.home__launch-btn--disabled {
  background: var(--accent-disabled);
  cursor: not-allowed;
  color: var(--text-3);
}
.home__launch-icon {
  display: block;
}

/* 下载区：次要信息，卡片弱化处理 */
.home__download {
  background: var(--panel-solid);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  padding: var(--sp-5) var(--sp-6);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.home__dl-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
}

.home__subheading {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  margin: 0;
}

.home__dl-hint {
  font-size: 11px;
  color: var(--text-4);
  flex-shrink: 0;
}

/* 免责声明：语义警示色 + 左粗边，与全局提示条一致 */
.home__disclaimer {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-2);
  font-size: 12px;
  line-height: 1.7;
  color: var(--warn-text);
  background: var(--warn-bg);
  padding: 9px 12px;
  border-radius: var(--r-sm);
  border-left: 3px solid currentColor;
}
.home__disclaimer-icon {
  flex-shrink: 0;
  margin-top: 2px;
  color: inherit;
}

.home__dl-meta {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.home__dl-meta-item {
  display: flex;
  gap: var(--sp-2);
  font-size: 12px;
  line-height: 1.5;
}
.home__meta-label {
  color: var(--text-3);
  flex-shrink: 0;
  min-width: 56px;
}
.home__meta-value {
  font-family: "Cascadia Code", "Consolas", "Menlo", monospace;
  color: var(--text-2);
  word-break: break-all;
}

.home__progress {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.home__progress-text {
  font-size: 11px;
  color: var(--text-3);
  text-align: right;
}

.home__dl-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  margin-top: 2px;
}

/* 官方QQ群宣传条 */
.home__qq {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  padding: var(--sp-3) var(--sp-4);
  background: var(--bg-soft-solid);
}
.home__qq-img {
  width: 56px;
  height: 56px;
  flex-shrink: 0;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: #ffffff;
  padding: 2px;
  object-fit: cover;
  -webkit-user-drag: none;
  user-select: none;
}
.home__qq-text {
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.7;
}
.home__qq-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}

/* 窄屏：单列布局，版本列表收进抽屉，左右留白收紧 */
@media (max-width: 960px) {
  .home {
    padding: var(--sp-5) var(--sp-4);
  }
  .home__main {
    max-width: 640px;
    width: 100%;
  }
}
</style>
