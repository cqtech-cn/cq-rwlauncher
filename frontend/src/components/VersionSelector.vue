<script setup lang="ts">
/**
 * 游戏版本选择面板。
 *
 * 作为首页右侧边栏的内容组件（窄屏时放进抽屉复用同一实例）。
 * 数据来自后端版本清单（默认 https://cdn.cqfishnet.cn/windows.json），
 * 安装走全局下载队列，完成后由后端切换启动定位。
 */
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import { versionApi, type VersionInfo, type EditionInfo } from '@/api/pywebview'
import { on, RW_EVENTS, type StatusEvent } from '@/api/events'
import { useDownloadsStore, fmt } from '@/stores/downloads'

const props = withDefaults(defineProps<{ launchArgs?: string }>(), { launchArgs: '' })

const emit = defineEmits<{
  /** 当前版本或已安装列表发生变化，父级应重新读取游戏状态 */
  (e: 'changed'): void
}>()

const { t } = useI18n()
const dlStore = useDownloadsStore()

const editions = ref<EditionInfo[]>([])
const selectedEdition = ref('')
const remoteVersions = ref<VersionInfo[]>([])
const installedVersions = ref<VersionInfo[]>([])
const currentVersion = ref('')
const latestVersion = ref('')
const loading = ref(false)
const loadError = ref('')

const switching = ref('')
const launching = ref('')
const uninstalling = ref('')
/** 版本号到下载任务 ID 的映射，用于读取真实进度 */
const taskMap = ref<Record<string, string>>({})

const installedSet = computed(() => new Set(installedVersions.value.map((v) => v.version)))
const hasMultipleEditions = computed(() => editions.value.length > 1)

/** 卡片列表：以远程清单为主，补齐仅本地存在（清单已下线）的版本 */
const versionList = computed<VersionInfo[]>(() => {
  const merged: VersionInfo[] = []
  const seen = new Set<string>()
  for (const v of remoteVersions.value) {
    if (seen.has(v.version)) continue
    seen.add(v.version)
    merged.push({ ...v, is_installed: installedSet.value.has(v.version) })
  }
  for (const v of installedVersions.value) {
    if (seen.has(v.version)) continue
    seen.add(v.version)
    merged.push(v)
  }
  return merged
})

const taskOf = (version: string) => {
  const taskId = taskMap.value[version]
  return taskId ? dlStore.get(taskId) : undefined
}

/** 该版本是否有正在进行的下载任务 */
const busyOf = (version: string) => {
  const status = taskOf(version)?.status
  return status === 'pending' || status === 'downloading' || status === 'extracting'
}

const pctOf = (version: string) => {
  const state = taskOf(version)
  if (!state || state.total <= 0) return 0
  return Math.min(100, Math.round((state.downloaded / state.total) * 100))
}

const indeterminateOf = (version: string) => {
  const state = taskOf(version)
  return state?.status === 'downloading' && state.total <= 0
}

const progressStatusOf = (version: string): 'success' | 'exception' | undefined => {
  const status = taskOf(version)?.status
  if (status === 'completed') return 'success'
  if (status === 'failed') return 'exception'
  return undefined
}

const statusTextOf = (version: string) => {
  const state = taskOf(version)
  if (!state) return ''
  switch (state.status) {
    case 'pending':
      return t('version.waiting')
    case 'downloading':
      return t('version.downloading')
    case 'extracting':
      return t('version.extracting')
    case 'completed':
      return t('version.done')
    case 'failed':
      return t('version.dlFailed')
    case 'canceled':
      return t('version.canceled')
    default:
      return ''
  }
}

/** 进度条右侧的大小 / 速度文本 */
const sizeTextOf = (version: string) => {
  const state = taskOf(version)
  if (!state) return ''
  if (state.status === 'extracting') return ''
  const downloaded = fmt.bytes(state.downloaded || 0)
  if (state.total > 0) {
    return `${downloaded} / ${fmt.bytes(state.total)}`
  }
  const speed = state.speed && state.speed > 0 ? ` · ${fmt.speed(state.speed)}` : ''
  return `${downloaded}${speed}`
}

/** 读取版本清单与本地安装情况 */
const loadVersions = async () => {
  const edition = selectedEdition.value || undefined
  const [installed, current] = await Promise.all([
    versionApi.getInstalledVersions(edition),
    versionApi.getCurrentVersion(),
  ])
  remoteVersions.value = editions.value.find((e) => e.name === edition)?.versions || []
  installedVersions.value = installed || []
  currentVersion.value = current || ''
  const matched = editions.value.find((e) => e.name === selectedEdition.value)
  latestVersion.value = matched?.latest_version || ''
}

/** 完整加载：清单 + 版本列表（失败时展示错误态，可手动重试） */
const load = async (withSpinner = true) => {
  if (withSpinner) loading.value = true
  loadError.value = ''
  try {
    if (withSpinner) await versionApi.clearCache()
    const catalog = await versionApi.getCatalog()
    editions.value = catalog.editions || []
    installedVersions.value = catalog.installed_versions || []
    currentVersion.value = catalog.current_version || ''
    if (!editions.value.some((e) => e.name === selectedEdition.value)) {
      const preferred = editions.value.find((e) => e.name === 'default')
      selectedEdition.value = preferred?.name || editions.value[0]?.name || ''
    }
    remoteVersions.value = editions.value.find((e) => e.name === selectedEdition.value)?.versions || []
    latestVersion.value = editions.value.find((e) => e.name === selectedEdition.value)?.latest_version || ''
    if (!catalog.ok) loadError.value = catalog.error || t('version.loadFailed')
  } catch (e: any) {
    loadError.value = e?.message || String(e)
  } finally {
    loading.value = false
  }
}

const onEditionChange = async () => {
  loading.value = true
  loadError.value = ''
  try {
    await loadVersions()
  } catch (e: any) {
    loadError.value = e?.message || String(e)
  } finally {
    loading.value = false
  }
}

/** 切换当前使用的版本（只改定位，不移动文件） */
const switchTo = async (version: string) => {
  if (version === currentVersion.value) {
    ElMessage.info(t('version.isCurrent'))
    return
  }
  try {
    await ElMessageBox.confirm(
      t('version.switchConfirmMsg', { version }),
      t('version.switchConfirmTitle'),
      {
        type: 'warning',
        confirmButtonText: t('version.switch'),
        cancelButtonText: t('common.cancel'),
      },
    )
  } catch {
    return
  }
  switching.value = version
  try {
    const res = await versionApi.switchVersion(version)
    if (!res.ok) {
      ElMessage.error(res.error || t('version.switchFailed'))
      return
    }
    currentVersion.value = res.current_version || version
    await loadVersions()
    emit('changed')
  } catch (e: any) {
    ElMessage.error(e?.message || t('version.switchFailed'))
  } finally {
    switching.value = ''
  }
}

/** 启动指定版本（成功后该版本即为当前版本） */
const launchVersion = async (version: string) => {
  launching.value = version
  try {
    const res = await versionApi.launchVersion(version, props.launchArgs || '')
    if (!res.ok) {
      if ((res as any).needs_jre) {
        ElMessage.warning(res.error || t('home.javaJreMissing'))
      } else {
        ElMessage.error(res.error || t('version.launchFailed'))
      }
      return
    }
    currentVersion.value = version
    ElMessage.success(t('home.gameLaunched'))
    emit('changed')
  } catch (e: any) {
    ElMessage.error(e?.message || t('version.launchFailed'))
  } finally {
    launching.value = ''
  }
}

/** 下载并安装指定版本（任务化，进度走全局下载事件） */
const doInstall = async (version: string) => {
  try {
    const res = await versionApi.installVersion(version, selectedEdition.value || undefined)
    if (!res.ok) {
      ElMessage.error(res.error || t('version.installFailed', { err: t('common.unknownError') }))
      return
    }
    if (res.already_installed) {
      ElMessage.info(t('version.alreadyInstalled', { version }))
      await loadVersions()
      return
    }
    if (res.task_id) {
      dlStore.add(res.task_id)
      taskMap.value = { ...taskMap.value, [version]: res.task_id }
      ElMessage.info(t('version.installStarted', { version }))
    }
  } catch (e: any) {
    ElMessage.error(t('version.installSubmitFailed', { err: e?.message || t('common.unknownError') }))
  }
}

/** 卸载指定版本（当前版本与运行中由后端拒绝） */
const uninstallVersion = async (version: string) => {
  try {
    await ElMessageBox.confirm(
      t('version.uninstallConfirmMsg', { version }),
      t('version.uninstallConfirmTitle'),
      {
        type: 'warning',
        confirmButtonText: t('version.uninstall'),
        cancelButtonText: t('common.cancel'),
      },
    )
  } catch {
    return
  }
  uninstalling.value = version
  try {
    const res = await versionApi.uninstallVersion(version)
    if (!res.ok) {
      ElMessage.error(res.error || t('version.uninstallFailed'))
      return
    }
    await loadVersions()
    emit('changed')
  } catch (e: any) {
    ElMessage.error(e?.message || t('version.uninstallFailed'))
  } finally {
    uninstalling.value = ''
  }
}

/** 版本安装任务结束时刷新列表并通知父级 */
const onStatus = async (d: StatusEvent) => {
  const version = Object.keys(taskMap.value).find((k) => taskMap.value[k] === d.task_id)
  if (!version) return
  if (d.status === 'failed') {
    ElMessage.error(d.error || t('version.dlFailed'))
  }
  if (d.status === 'completed' || d.status === 'failed' || d.status === 'canceled') {
    try {
      await loadVersions()
      emit('changed')
    } catch {
      // 列表刷新失败不阻塞后续操作
    }
  }
}

let unsubStatus: (() => void) | null = null

onMounted(async () => {
  unsubStatus = on<StatusEvent>(RW_EVENTS.STATUS, onStatus)
  await load()
})

onUnmounted(() => {
  if (unsubStatus) unsubStatus()
})

defineExpose({ reload: () => load(false) })
</script>

<template>
  <div class="vs">
    <header class="vs__head">
      <div class="vs__head-text">
        <h3 class="vs__title">{{ t('version.title') }}</h3>
        <p class="vs__sub">{{ t('version.sub') }}</p>
      </div>
      <button
        class="vs__icon-btn"
        type="button"
        :title="t('version.refresh')"
        :disabled="loading"
        @click="load()"
      >
        <svg viewBox="0 0 16 16" width="13" height="13" aria-hidden="true">
          <path
            d="M13 8a5 5 0 1 1-1.6-3.66M13 2.6V6h-3.4"
            fill="none"
            stroke="currentColor"
            stroke-width="1.4"
            stroke-linecap="round"
            stroke-linejoin="round"
          />
        </svg>
      </button>
    </header>

    <div class="vs__current">
      <span class="vs__current-label">{{ t('version.current') }}</span>
      <span :class="['vs__current-value', { 'vs__current-value--none': !currentVersion }]">
        {{ currentVersion || t('version.none') }}
      </span>
    </div>

    <div v-if="hasMultipleEditions" class="vs__editions">
      <span class="vs__editions-label">{{ t('version.editionLabel') }}</span>
      <el-select v-model="selectedEdition" size="small" @change="onEditionChange">
        <el-option v-for="ed in editions" :key="ed.name" :label="ed.name" :value="ed.name" />
      </el-select>
    </div>

    <div class="vs__list">
      <div v-if="loading" class="vs__state">
        <span class="vs__spinner" />
        <span>{{ t('version.loading') }}</span>
      </div>

      <div v-if="!loading && loadError" class="vs__state vs__state--error">
        <span>{{ t('version.loadFailed') }}：{{ loadError }}</span>
        <button class="vs__text-btn" type="button" @click="load()">{{ t('version.retry') }}</button>
      </div>

      <div v-if="!loading && !loadError && !versionList.length" class="vs__state">
        <span>{{ t('version.empty') }}</span>
      </div>

      <article
        v-for="item in versionList"
        v-if="!loading"
        :key="item.version"
        :class="['vs__card', { 'vs__card--current': item.version === currentVersion }]"
      >
        <div class="vs__card-top">
          <span class="vs__ver">{{ item.version }}</span>
          <span v-if="item.version === latestVersion" class="vs__chip vs__chip--latest">
            {{ t('version.latestTag') }}
          </span>
          <span v-if="item.version === currentVersion" class="vs__chip vs__chip--ok">
            {{ t('version.currentTag') }}
          </span>
        </div>

        <div class="vs__meta">
          <span :class="['vs__dot', item.is_installed ? 'vs__dot--on' : 'vs__dot--off']" />
          <span>{{ item.is_installed ? t('version.installed') : t('version.notInstalled') }}</span>
          <span v-if="item.build_date" class="vs__meta-sep">·</span>
          <span v-if="item.build_date">{{ item.build_date }}</span>
        </div>

        <p v-if="item.description" class="vs__desc">{{ item.description }}</p>

        <div v-if="taskOf(item.version)" class="vs__progress">
          <el-progress
            :percentage="pctOf(item.version)"
            :indeterminate="indeterminateOf(item.version)"
            :status="progressStatusOf(item.version)"
            :stroke-width="5"
            :show-text="false"
          />
          <div class="vs__progress-text">
            <span>{{ statusTextOf(item.version) }}</span>
            <span>{{ sizeTextOf(item.version) }}</span>
          </div>
        </div>

        <div class="vs__actions">
          <el-button
            v-if="item.is_installed && item.version !== currentVersion"
            size="small"
            :loading="switching === item.version"
            :disabled="busyOf(item.version)"
            @click="switchTo(item.version)"
          >
            {{ t('version.switch') }}
          </el-button>

          <el-button
            v-if="item.is_installed"
            size="small"
            type="primary"
            :loading="launching === item.version"
            @click="launchVersion(item.version)"
          >
            {{ t('version.launch') }}
          </el-button>

          <el-button
            v-if="item.is_installed && item.version !== currentVersion"
            size="small"
            type="danger"
            plain
            :loading="uninstalling === item.version"
            :disabled="busyOf(item.version)"
            @click="uninstallVersion(item.version)"
          >
            {{ t('version.uninstall') }}
          </el-button>

          <el-button
            v-if="!item.is_installed"
            size="small"
            type="primary"
            :loading="busyOf(item.version)"
            :disabled="busyOf(item.version)"
            @click="doInstall(item.version)"
          >
            {{ t('version.install') }}
          </el-button>
        </div>
      </article>
    </div>
  </div>
</template>

<style scoped>
.vs {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  min-width: 0;
}

/* 头部：标题 + 刷新 */
.vs__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: var(--sp-2);
}

.vs__head-text {
  min-width: 0;
}

.vs__title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  margin: 0 0 3px;
  line-height: 1.3;
}

.vs__sub {
  font-size: 11px;
  color: var(--text-4);
  margin: 0;
  line-height: 1.5;
}

.vs__icon-btn {
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 26px;
  height: 26px;
  flex-shrink: 0;
  padding: 0;
  color: var(--text-3);
  background: transparent;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  cursor: pointer;
  transition: color var(--dur-1) var(--ease), border-color var(--dur-1) var(--ease),
    background-color var(--dur-1) var(--ease);
}

.vs__icon-btn:hover:not(:disabled) {
  color: var(--accent);
  border-color: color-mix(in srgb, var(--accent) 45%, transparent);
  background: var(--hover-tint);
}

.vs__icon-btn:disabled {
  color: var(--accent-disabled);
  cursor: not-allowed;
}

/* 当前版本摘要 */
.vs__current {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
  padding: 10px var(--sp-3);
  background: var(--bg-soft-solid);
  border: 1px solid var(--border);
  border-left: 3px solid var(--accent);
  border-radius: var(--r-md);
}

.vs__current-label {
  font-size: 11px;
  color: var(--text-3);
  flex-shrink: 0;
}

.vs__current-value {
  font-family: "Cascadia Code", "Consolas", "Menlo", monospace;
  font-size: 12px;
  font-weight: 600;
  color: var(--text);
  text-align: right;
  word-break: break-all;
}

.vs__current-value--none {
  font-family: inherit;
  font-weight: 400;
  color: var(--text-4);
}

/* 分支选择 */
.vs__editions {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.vs__editions-label {
  font-size: 11px;
  color: var(--text-3);
  flex-shrink: 0;
}

.vs__editions :deep(.el-select) {
  flex: 1;
  min-width: 0;
}

/* 列表 */
.vs__list {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.vs__state {
  display: flex;
  align-items: center;
  justify-content: center;
  gap: var(--sp-2);
  padding: var(--sp-5) var(--sp-3);
  font-size: 12px;
  color: var(--text-4);
  background: var(--bg-soft-solid);
  border: 1px dashed var(--border);
  border-radius: var(--r-md);
  text-align: center;
}

.vs__state--error {
  flex-direction: column;
  color: var(--danger-text);
  border-color: color-mix(in srgb, var(--danger-text) 35%, transparent);
  background: color-mix(in srgb, var(--danger-text) 8%, transparent);
}

.vs__text-btn {
  padding: 0;
  font-size: 12px;
  color: var(--accent);
  background: none;
  border: none;
  cursor: pointer;
  text-decoration: underline;
}

.vs__spinner {
  width: 12px;
  height: 12px;
  border: 1.6px solid var(--border);
  border-top-color: var(--accent);
  border-radius: 50%;
  animation: vs-spin 0.8s linear infinite;
}

@keyframes vs-spin {
  to {
    transform: rotate(360deg);
  }
}

/* 版本卡片 */
.vs__card {
  display: flex;
  flex-direction: column;
  gap: 6px;
  padding: var(--sp-3);
  background: var(--panel-solid);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  transition: border-color var(--dur-2) var(--ease);
}

.vs__card:hover {
  border-color: color-mix(in srgb, var(--accent) 40%, transparent);
}

.vs__card--current {
  border-color: color-mix(in srgb, var(--accent) 55%, transparent);
  background: var(--selected-tint);
}

.vs__card-top {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
}

.vs__ver {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  word-break: break-all;
}

.vs__chip {
  display: inline-flex;
  align-items: center;
  padding: 1px 6px;
  font-size: 10px;
  font-weight: 600;
  border-radius: var(--r-full);
  flex-shrink: 0;
}

.vs__chip--ok {
  color: var(--on-accent);
  background: var(--accent);
}

.vs__chip--latest {
  color: var(--info-text);
  background: var(--info-bg);
}

.vs__meta {
  display: flex;
  align-items: center;
  gap: 5px;
  font-size: 11px;
  color: var(--text-3);
}

.vs__meta-sep {
  color: var(--text-4);
}

.vs__dot {
  width: 5px;
  height: 5px;
  border-radius: 50%;
  flex-shrink: 0;
}

.vs__dot--on {
  background: var(--success-text);
}

.vs__dot--off {
  background: var(--border);
}

.vs__desc {
  font-size: 11px;
  color: var(--text-2);
  line-height: 1.6;
  margin: 0;
  word-break: break-word;
}

.vs__progress {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.vs__progress-text {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-2);
  font-size: 10px;
  color: var(--text-3);
}

.vs__actions {
  display: flex;
  align-items: center;
  gap: 6px;
  flex-wrap: wrap;
  margin-top: 2px;
}

.vs__actions :deep(.el-button + .el-button) {
  margin-left: 0;
}
</style>
