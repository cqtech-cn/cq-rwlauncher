<script setup lang="ts">
/**
 * 服务可用性页：状态页风格（类似 status.deepseek.com）。
 * 数据由配套服务 /api/status 提供：公网服务探测 + 本机服务器资源 + 事件记录。
 * 同时提供 FRP 内网穿透管理。
 * 左侧边栏分页：实时状态 / 故障诊断（仅手动全项诊断） / 事件记录 / 服务器信息
 */
import { computed, onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { diagnoseApi, frpApi, platformApi, whenReady } from '@/api/pywebview'
import type { DiagnoseReport, FrpConfigData, FrpStatusData } from '@/api/pywebview'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

// 左侧边栏导航
const sidebarSections = [
  { key: 'status', label: '实时状态' },
  { key: 'diagnose', label: '故障诊断' },
  { key: 'events', label: '事件记录' },
  { key: 'server', label: '服务器信息' },
]
const activeSection = ref('status')

// —— 状态页 ——
interface SvcItem {
  name: string
  url: string
  status: 'normal' | 'down'
  latency_ms?: number
  uptime_7d?: number
  detail?: string
  note?: string
}
interface SvrInfo {
  hostname?: string
  memory_percent?: number | null
  disk_percent?: number | null
  uptime_hours?: number | null
}
interface StatusEvent {
  service: string
  level: string
  detail?: string
  time?: string
}

const loading = ref(false)
const lastError = ref('')
const checkedAt = ref('')
const services = ref<SvcItem[]>([])
const server = ref<SvrInfo>({})
const events = ref<StatusEvent[]>([])
const autoRefresh = ref(true)
let timer: number | null = null

const MAX_EVENTS = 200
const EVENT_PAGE_SIZE = 15
const eventPage = ref(1)
const totalEventPages = computed(() => Math.max(1, Math.ceil(events.value.length / EVENT_PAGE_SIZE)))
const displayedEvents = computed(() => {
  const start = (eventPage.value - 1) * EVENT_PAGE_SIZE
  return events.value.slice(start, start + EVENT_PAGE_SIZE)
})
const totalEventCount = computed(() => events.value.length)

const downCount = computed(() => services.value.filter((s) => s.status === 'down').length)
const overallOk = computed(() => services.value.length > 0 && downCount.value === 0)
const overallLabel = computed(() => {
  if (services.value.length === 0) return t('status.noData')
  return overallOk.value ? t('status.allOk') : t('status.downCount', { count: downCount.value })
})

const fmtPct = (v?: number | null) => (v == null ? '--' : v.toFixed(1) + '%')
const fmtHours = (v?: number | null) => {
  if (v == null) return '--'
  if (v >= 24) return (v / 24).toFixed(1) + t('status.days')
  return v.toFixed(1) + t('status.hours')
}

const load = async () => {
  loading.value = true
  lastError.value = ''
  try {
    const r = await platformApi.status()
    if (r.ok && r.data) {
      const d = r.data
      checkedAt.value = d.checked_at || ''
      services.value = d.services || []
      server.value = d.server || {}
      events.value = d.events || []
    } else {
      lastError.value = r.error || t('status.msg.fetchFailed')
      services.value = []
      server.value = {}
      events.value = []
    }
  } catch (e: any) {
    lastError.value = e?.message || t('status.msg.fetchFailed')
    services.value = []
    server.value = {}
    events.value = []
  } finally {
    loading.value = false
  }
}

// —— FRP 内网穿透 ——
const frpCfg = ref<FrpConfigData>({
  enabled: false,
  server_addr: '',
  server_port: 7000,
  auth_token: '',
  proxy_name: 'rw-game',
  proxy_type: 'tcp',
  local_ip: '127.0.0.1',
  local_port: 5123,
  frpc_path: '',
})
const frpStatus = ref<FrpStatusData>({
  installed: false,
  frpc_path: '',
  running: false,
  pid: 0,
  config_path: '',
  last_error: '',
  last_log_lines: [],
})
const frpSaving = ref(false)
const frpActing = ref(false)

const loadFrp = async () => {
  try {
    const r = await frpApi.getConfig()
    if (r.ok && r.config) frpCfg.value = { ...frpCfg.value, ...r.config }
    const s = await frpApi.status()
    if (s.ok && s.status) frpStatus.value = s.status
  } catch { /* 离线/未启用 静默 */ }
}

const onSaveFrp = async () => {
  frpSaving.value = true
  try {
    const r = await frpApi.setConfig({
      server_addr: frpCfg.value.server_addr.trim(),
      server_port: Number(frpCfg.value.server_port) || 7000,
      auth_token: frpCfg.value.auth_token,
      proxy_name: frpCfg.value.proxy_name.trim() || 'rw-game',
      proxy_type: frpCfg.value.proxy_type,
      local_ip: frpCfg.value.local_ip.trim() || '127.0.0.1',
      local_port: Number(frpCfg.value.local_port) || 5123,
      frpc_path: frpCfg.value.frpc_path.trim(),
    })
    if (r.ok && r.config) {
      frpCfg.value = r.config
      ElMessage.success(t('status.msg.configSaved'))
    } else {
      ElMessage.error(r.error || t('status.msg.saveFailed'))
    }
  } catch (e: any) {
    ElMessage.error(t('status.msg.saveFailedErr', { err: e?.message || t('common.unknownError') }))
  } finally {
    frpSaving.value = false
  }
}

const onStartFrp = async () => {
  await onSaveFrp()
  frpActing.value = true
  try {
    const r = await frpApi.start()
    if (r.ok) {
      ElMessage.success(r.already_running ? t('status.msg.frpAlreadyRunning') : t('status.msg.frpStarted'))
      await loadFrp()
    } else {
      ElMessage.error(r.error || t('status.msg.startFailed'))
    }
  } catch (e: any) {
    ElMessage.error(t('status.msg.startFailedErr', { err: e?.message || t('common.unknownError') }))
  } finally {
    frpActing.value = false
  }
}

const onStopFrp = async () => {
  frpActing.value = true
  try {
    const r = await frpApi.stop()
    if (r.ok) {
      ElMessage.success(r.already_stopped ? t('status.msg.frpNotRunning') : t('status.msg.frpStopped'))
      await loadFrp()
    } else {
      ElMessage.error(r.error || t('status.msg.stopFailed'))
    }
  } catch (e: any) {
    ElMessage.error(t('status.msg.stopFailedErr', { err: e?.message || t('common.unknownError') }))
  } finally {
    frpActing.value = false
  }
}

const onRefreshFrp = async () => {
  await loadFrp()
  if (frpStatus.value.running) {
    ElMessage.success(t('status.msg.frpRunningPid', { pid: frpStatus.value.pid }))
  } else if (frpStatus.value.installed) {
    ElMessage.info(t('status.msg.frpIdle'))
  } else {
    ElMessage.warning(t('status.msg.frpMissing'))
  }
}

// —— 手动诊断（自动监控 / 自动告警已移除） ——
const diagnosing = ref(false)
const report = ref<DiagnoseReport | null>(null)

const onRunDiagnosis = async () => {
  diagnosing.value = true
  try {
    report.value = await diagnoseApi.run()
  } catch (e: any) {
    ElMessage.error(t('settings.diagnose.failed', { err: e?.message || t('common.unknownError') }))
  } finally {
    diagnosing.value = false
  }
}

const onOpenSection = (e: Event) => {
  const id = (e as CustomEvent<string>).detail
  if (id === 'diagnose') {
    activeSection.value = 'diagnose'
  }
}

const toggleAutoRefresh = () => {
  autoRefresh.value = !autoRefresh.value
  if (autoRefresh.value) {
    load()
    timer = window.setInterval(load, 30000)
  } else if (timer != null) {
    window.clearInterval(timer)
    timer = null
  }
}

onMounted(async () => {
  await whenReady()
  await load()
  await loadFrp()
  if (autoRefresh.value) {
    timer = window.setInterval(load, 30000)
  }
  window.addEventListener('rw:open:settings-section', onOpenSection)
})

onUnmounted(() => {
  if (timer != null) {
    window.clearInterval(timer)
    timer = null
  }
  window.removeEventListener('rw:open:settings-section', onOpenSection)
})
</script>

<template>
  <div class="status-page">
    <!-- 左侧边栏 -->
    <aside class="status-page__side">
      <div class="status-page__side-title">状态</div>
      <nav class="status-page__nav">
        <button
          v-for="sec in sidebarSections"
          :key="sec.key"
          class="status-page__nav-item"
          :class="{ 'is-active': activeSection === sec.key }"
          @click="activeSection = sec.key"
        >
          {{ sec.label }}
        </button>
      </nav>
    </aside>

    <!-- 右侧内容 -->
    <div class="status-page__main">
      <div class="status-page__inner">

        <!-- 实时状态 -->
        <div v-show="activeSection === 'status'" class="status-page__panel">
          <div class="status__banner" :class="overallOk ? 'status__banner--ok' : 'status__banner--bad'">
            <div class="status__banner-icon">
              <svg v-if="overallOk" viewBox="0 0 48 48" width="34" height="34" aria-hidden="true">
                <circle cx="24" cy="24" r="20" fill="none" stroke="currentColor" stroke-width="3"/>
                <path d="M16 24.5l5.5 5.5L32 18.5" fill="none" stroke="currentColor" stroke-width="4" stroke-linecap="round" stroke-linejoin="round"/>
              </svg>
              <svg v-else viewBox="0 0 48 48" width="34" height="34" aria-hidden="true">
                <path d="M24 5 43 40H5L24 5z" fill="none" stroke="currentColor" stroke-width="3" stroke-linejoin="round"/>
                <line x1="24" y1="16" x2="24" y2="28" stroke="currentColor" stroke-width="3.5" stroke-linecap="round"/>
                <circle cx="24" cy="35" r="2.4" fill="currentColor"/>
              </svg>
            </div>
            <div class="status__banner-main">
              <div class="status__banner-label">{{ t('status.bannerLabel') }}</div>
              <div class="status__banner-value">{{ lastError ? t('status.fetchFailed') : overallLabel }}</div>
              <div class="status__banner-meta">
                <span v-if="checkedAt">{{ t('status.lastChecked', { time: checkedAt }) }}</span>
                <span v-else-if="lastError" class="status__banner-err">{{ lastError }}</span>
                <span v-else>{{ t('status.connecting') }}</span>
              </div>
            </div>
            <div class="status__banner-actions">
              <button class="status__banner-btn" :disabled="loading" @click="load">
                <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
                  <path d="M13 8a5 5 0 1 1-1.5-3.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                  <path d="M13 2v3.5h-3.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
                </svg>
                <span>{{ loading ? t('status.checking') : t('status.recheck') }}</span>
              </button>
              <label class="status__autorefresh">
                <el-switch v-model="autoRefresh" @change="toggleAutoRefresh" size="small" />
                <span>{{ t('status.autoRefresh') }}</span>
              </label>
            </div>
          </div>

          <!-- 服务列表 -->
          <section class="status__section">
            <h2 class="status__section-title">{{ t('status.components') }}</h2>
            <div v-if="lastError" class="status__error">{{ lastError }}</div>
            <div v-else-if="services.length === 0 && !loading" class="status__empty">{{ t('status.empty') }}</div>
            <div v-else class="status__list">
              <div v-for="(it, i) in services" :key="i" class="status__item" :class="it.status === 'down' ? 'status__item--down' : ''">
                <span :class="['status__dot', it.status === 'normal' ? 'status__dot--ok' : 'status__dot--bad']" />
                <div class="status__item-body">
                  <div class="status__item-name">{{ it.name }}</div>
                  <div class="status__item-url text-mono">{{ it.url }}</div>
                  <span v-if="it.status === 'down' && (it.note || it.detail)" class="status__note" :title="it.note || it.detail">{{ it.note || it.detail }}</span>
                </div>
                <div class="status__item-right">
                  <span v-if="it.uptime_7d != null" class="status__uptime" :class="it.uptime_7d >= 100 ? 'status__uptime--ok' : 'status__uptime--warn'">
                    <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
                      <circle cx="8" cy="8" r="6" fill="none" stroke="currentColor" stroke-width="1.5"/>
                      <path d="M8 4.5V8l2.5 1.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
                    </svg>
                    <span>{{ t('status.uptime', { value: it.uptime_7d }) }}</span>
                  </span>
                  <span v-if="it.latency_ms != null" class="status__latency">{{ it.latency_ms }} ms</span>
                  <span :class="['status__badge', it.status === 'normal' ? 'status__badge--ok' : 'status__badge--bad']">
                    {{ it.status === 'normal' ? t('status.normal') : t('status.down') }}
                  </span>
                </div>
              </div>
            </div>
          </section>

          <!-- FRP 内网穿透 -->
          <section class="status__section">
            <h2 class="status__section-title">FRP 内网穿透</h2>
            <div class="status__row">
              <span class="status__label">启用</span>
              <el-switch v-model="frpCfg.enabled" />
            </div>
            <div class="status__row">
              <span class="status__label">服务器</span>
              <input v-model="frpCfg.server_addr" class="status__input" placeholder="frps.example.com" />
            </div>
            <div class="status__row">
              <span class="status__label">端口</span>
              <input v-model.number="frpCfg.server_port" class="status__input status__input--short" type="number" placeholder="7000" />
            </div>
            <div class="status__row">
              <span class="status__label">Token</span>
              <input v-model="frpCfg.auth_token" class="status__input" type="password" placeholder="认证令牌" />
            </div>
            <div class="status__row">
              <span class="status__label">代理名</span>
              <input v-model="frpCfg.proxy_name" class="status__input" placeholder="rw-game" />
            </div>
            <div class="status__row">
              <span class="status__label">本地 IP</span>
              <input v-model="frpCfg.local_ip" class="status__input status__input--short" placeholder="127.0.0.1" />
            </div>
            <div class="status__row">
              <span class="status__label">本地端口</span>
              <input v-model.number="frpCfg.local_port" class="status__input status__input--short" type="number" placeholder="5123" />
            </div>
            <div class="status__row">
              <span class="status__label">状态</span>
              <span :class="['status__badge', frpStatus.running ? 'status__badge--ok' : frpStatus.installed ? 'status__badge--warn' : 'status__badge--off']">
                {{ frpStatus.running ? '运行中' : frpStatus.installed ? '已停止' : '未安装' }}
              </span>
              <span v-if="frpStatus.running" class="status__code">PID: {{ frpStatus.pid }}</span>
            </div>
            <div class="status__actions">
              <el-button size="small" type="primary" :loading="frpSaving" @click="onSaveFrp">保存配置</el-button>
              <el-button size="small" type="success" :loading="frpActing" @click="onStartFrp" :disabled="!frpCfg.enabled">启动</el-button>
              <el-button size="small" :loading="frpActing" @click="onStopFrp">停止</el-button>
              <el-button size="small" @click="onRefreshFrp">刷新</el-button>
            </div>
            <div v-if="frpStatus.last_error" class="status__error">{{ frpStatus.last_error }}</div>
            <div v-if="frpStatus.last_log_lines.length" class="frp-log">{{ frpStatus.last_log_lines.join('\n') }}</div>
          </section>
        </div>

        <!-- 手动诊断 -->
        <div v-show="activeSection === 'diagnose'" class="status-page__panel">
          <section class="status__section">
            <h2 class="status__section-title">{{ t('settings.diagnose.title') }}</h2>
            <div class="status__hint">{{ t('settings.diagnose.hint') }}</div>
            <div class="status__row status__row--top">
              <span class="status__label">{{ t('settings.diagnose.full') }}</span>
              <div class="diag__report">
                <div class="diag__report-actions">
                  <el-button type="primary" size="small" :loading="diagnosing" @click="onRunDiagnosis">
                    {{ t('settings.diagnose.run') }}
                  </el-button>
                  <span v-if="report" class="diag__summary">{{ report.summary }}（{{ report.checked_at }}）</span>
                </div>
                <div v-if="report" class="diag__items">
                  <div v-for="it in report.items" :key="it.id" class="diag__item">
                    <span :class="['diag__dot', `diag__dot--${it.status}`]" />
                    <span class="diag__item-label">{{ it.label }}</span>
                    <span class="diag__item-msg">{{ it.message }}</span>
                  </div>
                </div>
              </div>
            </div>
          </section>
        </div>

        <!-- 事件记录 -->
        <div v-show="activeSection === 'events'" class="status-page__panel">
          <section v-if="events.length" class="status__section">
            <h2 class="status__section-title">{{ t('status.events') }}
              <span class="status__events-count">（{{ totalEventCount }} 条）</span>
            </h2>
            <div v-if="!events.length && !loading" class="status__empty">暂无事件记录</div>
            <div class="status__events">
              <div v-for="(e, i) in displayedEvents" :key="i" class="status__event" :class="e.level === 'down' ? 'status__event--down' : 'status__event--ok'">
                <span :class="['status__dot', e.level === 'down' ? 'status__dot--bad' : 'status__dot--ok']" />
                <span class="status__event-time text-mono">{{ e.time }}</span>
                <span class="status__event-service">{{ e.service }}</span>
                <span :class="['status__badge', e.level === 'down' ? 'status__badge--bad' : 'status__badge--ok']">
                  {{ e.level === 'down' ? t('status.down') : t('status.eventNormal') }}
                </span>
                <span v-if="e.detail" class="status__event-detail" :title="e.detail">{{ e.detail }}</span>
              </div>
            </div>
            <div v-if="totalEventPages > 1" class="status__pagination">
              <button class="status__page-btn" :disabled="eventPage <= 1" @click="eventPage = Math.max(1, eventPage - 1)">
                <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M10 3L5 8l5 5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
              </button>
              <span class="status__page-info">{{ eventPage }} / {{ totalEventPages }}</span>
              <button class="status__page-btn" :disabled="eventPage >= totalEventPages" @click="eventPage = Math.min(totalEventPages, eventPage + 1)">
                <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true"><path d="M6 3l5 5-5 5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/></svg>
              </button>
            </div>
          </section>
          <div v-else-if="!loading" class="status__empty">暂无事件记录</div>
        </div>

        <!-- 服务器信息 -->
        <div v-show="activeSection === 'server'" class="status-page__panel">
          <section v-if="server.hostname" class="status__section">
            <h2 class="status__section-title">{{ t('status.localServer') }}</h2>
            <div class="status__server">
              <div class="status__server-item">
                <span class="status__server-label">{{ t('status.hostname') }}</span>
                <span class="status__server-value text-mono">{{ server.hostname }}</span>
              </div>
              <div class="status__server-item">
                <span class="status__server-label">{{ t('status.memory') }}</span>
                <span class="status__server-value">{{ fmtPct(server.memory_percent) }}</span>
              </div>
              <div class="status__server-item">
                <span class="status__server-label">{{ t('status.disk') }}</span>
                <span class="status__server-value">{{ fmtPct(server.disk_percent) }}</span>
              </div>
              <div class="status__server-item">
                <span class="status__server-label">{{ t('status.runTime') }}</span>
                <span class="status__server-value">{{ fmtHours(server.uptime_hours) }}</span>
              </div>
            </div>
          </section>
          <div v-else-if="!loading" class="status__empty">暂无服务器信息</div>
        </div>

      </div>
    </div>
  </div>
</template>

<style scoped>
/* 布局 */
.status-page {
  display: flex;
  height: 100%;
  width: 100%;
}

/* 左侧边栏 */
.status-page__side {
  width: 160px;
  flex-shrink: 0;
  padding: var(--sp-6) 0;
  border-right: 1px solid var(--border);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  background: var(--bg-mid-solid);
}

.status-page__side-title {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-3);
  padding: 0 var(--sp-5) var(--sp-3);
  letter-spacing: 1px;
}

.status-page__nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 var(--sp-2);
}

.status-page__nav-item {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  width: 100%;
  padding: 10px 14px;
  font-size: 13px;
  color: var(--text-2);
  background: none;
  border: none;
  text-align: left;
  cursor: pointer;
  border-radius: var(--r-sm);
  transition: background-color var(--dur-1) var(--ease), color var(--dur-1) var(--ease);
}

.status-page__nav-item:hover {
  background: var(--hover-tint);
  color: var(--text);
}

.status-page__nav-item.is-active {
  background: var(--selected-tint);
  color: var(--text);
  font-weight: 600;
}

/* 右侧主内容区 */
.status-page__main {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  background: transparent;
}

.status-page__inner {
  max-width: 780px;
  width: 100%;
  margin: 0 auto;
  padding: var(--sp-8) var(--sp-6) 40px;
  display: flex;
  flex-direction: column;
  gap: var(--sp-6);
}

.status-page__panel {
  display: flex;
  flex-direction: column;
  gap: var(--sp-6);
}

/* 通用区块 */
.status__section {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.status__section-title {
  position: relative;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  padding-bottom: var(--sp-2);
}
.status__section-title::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 1px;
  background: linear-gradient(90deg, var(--border), transparent);
}
.status__events-count {
  font-size: 11px;
  font-weight: 400;
  color: var(--text-4);
  margin-left: 6px;
}
.status__hint {
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.7;
  padding: 10px var(--sp-3);
  background: var(--info-bg);
  border-radius: var(--r-sm);
}
.status__row {
  display: flex;
  align-items: center;
  gap: 12px;
}
.status__row--top {
  align-items: flex-start;
}
.status__hint-inline {
  font-size: 11px;
  color: var(--text-4);
}
.status__code {
  font-size: 11px;
  color: var(--text-3);
  font-family: 'Cascadia Code', 'Consolas', monospace;
  word-break: break-all;
}
.status__label {
  width: 96px;
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-3);
}
.status__actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}

/* 横幅 */
.status__banner {
  position: relative;
  display: flex;
  align-items: center;
  gap: var(--sp-5);
  padding: var(--sp-5) var(--sp-6);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-1);
  overflow: hidden;
}
.status__banner::before {
  content: '';
  position: absolute;
  inset: 0;
  pointer-events: none;
}
.status__banner--ok {
  background: linear-gradient(120deg, var(--success-bg), transparent 78%);
  border-color: color-mix(in srgb, var(--success-text) 45%, transparent);
}
.status__banner--bad {
  background: linear-gradient(120deg, var(--danger-bg), transparent 78%);
  border-color: color-mix(in srgb, var(--danger-text) 45%, transparent);
}
.status__banner-icon {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  width: 56px;
  height: 56px;
  border-radius: var(--r-full);
  background: color-mix(in srgb, var(--text) 5%, transparent);
}
.status__banner--ok .status__banner-icon { color: var(--success-text); }
.status__banner--bad .status__banner-icon { color: var(--danger-text); }
.status__banner-main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}
.status__banner-label {
  font-size: 12px;
  letter-spacing: 2px;
  opacity: 0.75;
}
.status__banner--ok .status__banner-label { color: var(--success-text); }
.status__banner--bad .status__banner-label { color: var(--danger-text); }
.status__banner-value {
  font-size: 24px;
  font-weight: 700;
  line-height: 1.25;
}
.status__banner--ok .status__banner-value { color: var(--success-text); }
.status__banner--bad .status__banner-value { color: var(--danger-text); }
.status__banner-meta {
  display: flex;
  align-items: center;
  gap: 12px;
  font-size: 11px;
  color: var(--text-3);
  flex-wrap: wrap;
}
.status__banner-err {
  color: var(--danger-text);
  max-width: 380px;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
.status__banner-actions {
  flex-shrink: 0;
  display: flex;
  flex-direction: column;
  align-items: flex-end;
  gap: 10px;
}
.status__banner-btn {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  padding: 8px var(--sp-4);
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  background: var(--panel-solid);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  cursor: pointer;
  transition: border-color var(--dur-1) var(--ease), color var(--dur-1) var(--ease);
}
.status__banner-btn:hover:not(:disabled) {
  border-color: var(--accent);
  color: var(--accent);
}
.status__banner-btn:active:not(:disabled) {
  background: var(--press-tint);
}
.status__banner-btn:disabled {
  opacity: 0.55;
  cursor: default;
}
.status__autorefresh {
  display: inline-flex;
  align-items: center;
  gap: 6px;
  font-size: 11px;
  color: var(--text-3);
  cursor: pointer;
}

/* 服务列表 */
.status__list {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(300px, 1fr));
  gap: 10px;
}
.status__item {
  display: flex;
  align-items: center;
  gap: 14px;
  padding: 14px var(--sp-4);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  background: var(--panel-solid);
  box-shadow: var(--shadow-1);
  transition: border-color var(--dur-1) var(--ease);
}
.status__item:hover { border-color: var(--text-3); }
.status__item--down { border-color: color-mix(in srgb, var(--danger-text) 45%, transparent); background: var(--danger-bg); }
.status__dot {
  flex-shrink: 0;
  width: 10px;
  height: 10px;
  border-radius: var(--r-full);
}
.status__dot--ok { background: var(--success-text); box-shadow: 0 0 0 4px var(--success-bg); }
.status__dot--bad { background: var(--danger-text); box-shadow: 0 0 0 4px var(--danger-bg); }
.status__item-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.status__item-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
}
.status__item-url {
  font-size: 11px;
  color: var(--text-4);
  word-break: break-all;
}
.status__item-right {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 12px;
}
.status__uptime {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  font-family: 'Cascadia Code', 'Consolas', monospace;
}
.status__uptime--ok { color: var(--success-text); }
.status__uptime--warn { color: var(--warn-text); }
.status__badge {
  padding: 3px 10px;
  font-size: 11px;
  font-weight: 600;
  border-radius: var(--r-full);
}
.status__badge--ok { background: var(--success-bg); color: var(--success-text); }
.status__badge--bad { background: var(--danger-bg); color: var(--danger-text); }
.status__badge--off { background: var(--border-soft); color: var(--text-3); }
.status__badge--warn { background: var(--warn-bg); color: var(--warn-text); }
.status__latency {
  font-size: 11px;
  color: var(--text-3);
  font-family: 'Cascadia Code', 'Consolas', monospace;
}
.status__note {
  font-size: 11px;
  line-height: 1.5;
  color: var(--danger-text);
  max-width: 100%;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 错误 / 空状态 */
.status__error {
  padding: var(--sp-3) 14px;
  border: 1px solid color-mix(in srgb, var(--danger-text) 40%, transparent);
  border-radius: var(--r-sm);
  background: var(--danger-bg);
  color: var(--danger-text);
  font-size: 12px;
  line-height: 1.6;
}
.status__empty {
  padding: var(--sp-5);
  text-align: center;
  font-size: 12px;
  color: var(--text-4);
  border: 1px dashed var(--border);
  border-radius: var(--r-md);
}

/* 服务器信息 */
.status__server {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(150px, 1fr));
  gap: 10px;
}
.status__server-item {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--sp-3) 14px;
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  background: var(--panel-solid);
  box-shadow: var(--shadow-1);
}
.status__server-label {
  font-size: 11px;
  color: var(--text-4);
}
.status__server-value {
  font-size: 15px;
  font-weight: 600;
  color: var(--text);
}

/* 事件记录 */
.status__events {
  display: flex;
  flex-direction: column;
  gap: 8px;
}
.status__event {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px var(--sp-3);
  border: 1px solid var(--border);
  border-left-width: 3px;
  border-radius: var(--r-sm);
  background: var(--panel-solid);
  font-size: 12px;
}
.status__event--down { border-left-color: var(--danger-text); }
.status__event--ok { border-left-color: var(--success-text); }
.status__event-time {
  flex-shrink: 0;
  font-size: 11px;
  color: var(--text-3);
}
.status__event-service {
  font-weight: 500;
  color: var(--text);
  white-space: nowrap;
}
.status__event-detail {
  flex: 1;
  min-width: 0;
  color: var(--text-4);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 分页 */
.status__pagination {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2);
  padding: 10px 0 var(--sp-1);
}
.status__page-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 28px;
  height: 28px;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--panel-solid);
  color: var(--text);
  cursor: pointer;
  font-size: 12px;
  transition: border-color var(--dur-1) var(--ease), color var(--dur-1) var(--ease), background-color var(--dur-1) var(--ease);
}
.status__page-btn:hover:not(:disabled) { border-color: var(--accent); color: var(--accent); }
.status__page-btn:active:not(:disabled) { background: var(--press-tint); }
.status__page-btn:disabled { opacity: 0.4; cursor: default; }
.status__page-info {
  font-size: 12px;
  color: var(--text-3);
  min-width: 50px;
  text-align: center;
}

/* 输入框 */
.status__input {
  flex: 1;
  max-width: 240px;
  padding: 6px 10px;
  font-size: 12px;
  color: var(--text);
  background: var(--panel-solid);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  transition: border-color var(--dur-1) var(--ease), box-shadow var(--dur-1) var(--ease);
}
.status__input:focus { border-color: var(--accent); outline: none; box-shadow: var(--ring); }
.status__input--short { max-width: 120px; }

/* FRP 日志 */
.frp-log {
  width: 100%;
  max-height: 200px;
  overflow: auto;
  padding: 10px var(--sp-3);
  background: var(--bg-mid-solid);
  color: var(--text-2);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  font-family: 'Cascadia Code', 'Consolas', monospace;
  font-size: 12px;
  line-height: 1.5;
  white-space: pre;
}

/* 手动诊断 */
.diag__report {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.diag__report-actions {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-wrap: wrap;
}
.diag__summary {
  font-size: 12px;
  color: var(--text-3);
}
.diag__items {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.diag__item {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
  line-height: 1.5;
}
.diag__dot {
  width: 8px;
  height: 8px;
  border-radius: var(--r-full);
  flex-shrink: 0;
  margin-top: 5px;
}
.diag__dot--ok { background: var(--success-text); }
.diag__dot--warn { background: var(--warn-text); }
.diag__dot--error { background: var(--danger-text); }
.diag__dot--info { background: var(--text-4); }
.diag__item-label {
  width: 76px;
  flex-shrink: 0;
  color: var(--text-3);
}
.diag__item-msg {
  flex: 1;
  min-width: 0;
  color: var(--text-2);
  word-break: break-all;
}
</style>