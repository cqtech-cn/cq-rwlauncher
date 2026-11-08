<script setup lang="ts">
/**
 * 下载中心。
 * 左侧 sidebar：模组下载、地图下载、下载管理、下载设置
 * 右侧主区：根据 activeId 切换显示对应面板
 */
import { onMounted, ref, computed } from 'vue'
import { useI18n } from 'vue-i18n'
import { ElMessage, ElMessageBox } from 'element-plus'
import ResourceBrowser from '@/components/ResourceBrowser.vue'
import Icon from '@/components/Icon.vue'
import { useDownloadsStore, fmt } from '@/stores/downloads'
import { configApi, resourceApi, versionApi, whenReady } from '@/api/pywebview'

const { t } = useI18n()

type PanelId = 'mods' | 'maps' | 'manager' | 'settings'

const active = ref<PanelId>('mods')

const sidebarItems: { id: PanelId; label: string; icon: string }[] = [
  { id: 'mods', label: t('download.sidebar.mods'), icon: 'mod' },
  { id: 'maps', label: t('download.sidebar.maps'), icon: 'map' },
  { id: 'manager', label: t('download.sidebar.manager'), icon: 'list' },
  { id: 'settings', label: t('download.sidebar.settings'), icon: 'settings' },
]

const dlStore = useDownloadsStore()

const downloads = computed(() => dlStore.all())

// —— 下载设置：版本清单地址 / 限速 / 清除缓存（从设置页迁移） ——
const manifestUrl = ref('')
const limitKbps = ref(0)
const savingSettings = ref(false)
const checkingManifest = ref(false)

/** 保存清单地址与限速 */
const saveSettings = async () => {
  savingSettings.value = true
  try {
    // 限速：取整到 KB/s，非负数，NaN 视为不限
    const rawLimit = Number(limitKbps.value)
    const limit = Number.isFinite(rawLimit) && rawLimit > 0 ? Math.floor(rawLimit) : 0
    await configApi.update({
      game_version_list: { url: manifestUrl.value.trim() },
      download_speed_limit_kbps: limit,
    })
    manifestUrl.value = manifestUrl.value.trim()
    limitKbps.value = limit
    ElMessage.success(t('download.settings.saved'))
  } catch (e: any) {
    ElMessage.error(t('download.settings.saveFailed', { err: e?.message || t('common.unknownError') }))
  } finally {
    savingSettings.value = false
  }
}

/** 保存当前填写的清单地址并立即拉取一次，用于确认地址可用 */
const checkManifest = async () => {
  const url = manifestUrl.value.trim()
  if (!url) {
    ElMessage.warning(t('download.settings.checkNeedUrl'))
    return
  }
  checkingManifest.value = true
  try {
    // 保存清单地址（后端会顺带清掉远程清单缓存），再强制重新拉取一次
    await configApi.update({ game_version_list: { url } })
    manifestUrl.value = url
    const res = await versionApi.checkManifest()
    if (res.ok && (res.editions || 0) > 0) {
      ElMessage.success(t('download.settings.checkOk', { count: res.editions }))
    } else if (res.ok) {
      ElMessage.warning(t('download.settings.checkEmpty'))
    } else {
      ElMessage.error(t('download.settings.checkFailed', { err: res.error || t('common.unknownError') }))
    }
  } catch (e: any) {
    ElMessage.error(t('download.settings.checkFailed', { err: e?.message || t('common.unknownError') }))
  } finally {
    checkingManifest.value = false
  }
}

const loadSettings = async () => {
  try {
    const c = await configApi.get()
    manifestUrl.value = c.game_version_list?.url || ''
    limitKbps.value = Number(c.download_speed_limit_kbps) || 0
  } catch {}
}

// —— 清除缓存 ——
const cacheTargets = ref<string[]>([])
const clearing = ref(false)
const onClearCache = async () => {
  if (cacheTargets.value.length === 0) {
    ElMessage.warning(t('settings.cache.needSelect'))
    return
  }
  try {
    await ElMessageBox.confirm(
      t('settings.cache.confirmMsg'),
      t('settings.cache.confirmTitle'),
      { type: 'warning', confirmButtonText: t('settings.cache.confirmOk'), cancelButtonText: t('settings.cache.confirmCancel') },
    )
  } catch {
    return // 用户取消
  }
  clearing.value = true
  try {
    const res = await resourceApi.clearGameCache(cacheTargets.value)
    if (res.ok) {
      const parts: string[] = []
      if (res.removed.mods) parts.push(t('settings.cache.modItem', { count: res.removed.mods }))
      if (res.removed.maps) parts.push(t('settings.cache.mapItem', { count: res.removed.maps }))
      if (res.removed.saves) parts.push(t('settings.cache.saveItem', { count: res.removed.saves }))
      ElMessage.success(parts.length ? t('settings.cache.cleared', { parts: parts.join('，') }) : t('settings.cache.clearedAll'))
      await loadInstalled()
    } else {
      ElMessage.error(t('settings.cache.clearFailed', { err: res.error || t('common.unknownError') }))
    }
  } catch (e: any) {
    ElMessage.error(t('settings.cache.clearFailed', { err: e?.message || t('common.unknownError') }))
  } finally {
    clearing.value = false
  }
}

// —— 已安装资源（从设置页迁移） ——
const installedMods = ref<string[]>([])
const installedMaps = ref<string[]>([])
const loadInstalled = async () => {
  try {
    installedMods.value = await resourceApi.listInstalled('mod')
    installedMaps.value = await resourceApi.listInstalled('map')
  } catch {
    // 忽略
  }
}

onMounted(async () => {
  await whenReady()
  await loadSettings()
  await loadInstalled()
})
</script>

<template>
  <div class="dl">
    <aside class="dl__side">
      <div class="dl__side-title">{{ t('download.sidebar.title') }}</div>
      <nav class="dl__nav">
        <button
          v-for="s in sidebarItems"
          :key="s.id"
          :class="['dl__nav-item', { 'dl__nav-item--active': active === s.id }]"
          @click="active = s.id"
        >
          <Icon :name="s.icon" :size="14" />
          <span>{{ s.label }}</span>
        </button>
      </nav>
    </aside>

    <section class="dl__main">
      <div v-show="active === 'mods'" class="dl__panel">
        <ResourceBrowser kind="mod" />
      </div>
      <div v-show="active === 'maps'" class="dl__panel">
        <ResourceBrowser kind="map" />
      </div>

      <div v-show="active === 'manager'" class="dl__panel">
        <div class="dl__pane">
          <div class="dl__pane-header">
            <h2 class="dl__pane-title">{{ t('download.manager.title') }}</h2>
            <div class="dl__pane-sub">{{ t('download.manager.sub') }}</div>
          </div>
          <div v-if="downloads.length === 0" class="dl__empty">{{ t('download.manager.empty') }}</div>
          <div v-else class="dl__tasks">
            <div v-for="task in downloads" :key="task.task_id" class="dl__task">
              <div class="dl__task-head">
                <div class="dl__task-id text-mono">{{ task.task_id }}</div>
                <div :class="['dl__task-status', `dl__task-status--${task.status}`]">
                  {{ task.status }}
                </div>
              </div>
              <div class="dl__task-body">
                <div class="dl__task-meta">
                  <span>{{ fmt.bytes(task.downloaded) }}<span v-if="task.total"> / {{ fmt.bytes(task.total) }}</span></span>
                  <span v-if="task.speed && task.speed > 0">· {{ fmt.speed(task.speed) }}</span>
                  <span v-if="task.error" class="text-muted">{{ task.error }}</span>
                </div>
              </div>
            </div>
          </div>

          <!-- 已安装资源（从设置页迁移） -->
          <div class="dl__block">
            <div class="dl__block-title">{{ t('settings.installed.title') }}</div>
            <div class="dl__block-row">
              <span class="dl__block-label">{{ t('settings.installed.mods', { count: installedMods.length }) }}</span>
              <div v-if="installedMods.length === 0" class="dl__block-empty">{{ t('settings.installed.none') }}</div>
              <div v-else class="dl__tags">
                <el-tag v-for="m in installedMods" :key="m" size="small" type="info">{{ m }}</el-tag>
              </div>
            </div>
            <div class="dl__block-row">
              <span class="dl__block-label">{{ t('settings.installed.maps', { count: installedMaps.length }) }}</span>
              <div v-if="installedMaps.length === 0" class="dl__block-empty">{{ t('settings.installed.none') }}</div>
              <div v-else class="dl__tags">
                <el-tag v-for="m in installedMaps" :key="m" size="small" type="info">{{ m }}</el-tag>
              </div>
            </div>
          </div>
        </div>
      </div>

      <div v-show="active === 'settings'" class="dl__panel">
        <div class="dl__pane">
          <div class="dl__pane-header">
            <h2 class="dl__pane-title">{{ t('download.settings.title') }}</h2>
            <div class="dl__pane-sub">{{ t('download.settings.sub') }}</div>
          </div>
          <div class="dl__form">
            <div class="dl__form-row">
              <label class="dl__form-label">{{ t('download.settings.manifest') }}</label>
              <div class="dl__form-inline">
                <el-input v-model="manifestUrl" placeholder="https://..." />
                <el-button :loading="checkingManifest" @click="checkManifest">
                  {{ t('download.settings.check') }}
                </el-button>
              </div>
              <div class="dl__form-tip">{{ t('download.settings.manifestHint') }}</div>
            </div>
            <div class="dl__form-row">
              <label class="dl__form-label">{{ t('settings.limit.label') }}</label>
              <el-input-number
                v-model="limitKbps"
                :min="0"
                :step="64"
                :precision="0"
                controls-position="right"
                placeholder="0"
                class="dl__limit-input"
              />
              <div class="dl__form-tip">{{ t('settings.limit.hint') }}</div>
            </div>
            <div class="dl__form-action">
              <el-button type="primary" :loading="savingSettings" @click="saveSettings">{{ t('download.settings.save') }}</el-button>
            </div>
            <div class="dl__form-tip text-muted">
              {{ t('download.settings.tip') }}
            </div>
          </div>

          <!-- 清除缓存（从设置页迁移） -->
          <div class="dl__block">
            <div class="dl__block-title">{{ t('settings.cache.title') }}</div>
            <div class="dl__block-tip">{{ t('settings.cache.hint') }}</div>
            <div class="dl__cache-options">
              <el-checkbox-group v-model="cacheTargets">
                <div class="cache__options">
                  <el-checkbox value="mods">{{ t('settings.cache.mods') }}</el-checkbox>
                  <el-checkbox value="maps">{{ t('settings.cache.maps') }}</el-checkbox>
                  <el-checkbox value="saves">{{ t('settings.cache.saves') }}</el-checkbox>
                </div>
              </el-checkbox-group>
            </div>
            <el-button
              type="danger"
              :loading="clearing"
              :disabled="cacheTargets.length === 0"
              @click="onClearCache"
            >{{ t('settings.cache.clear') }}</el-button>
          </div>
        </div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.dl {
  display: flex;
  height: 100%;
  width: 100%;
  background: transparent;
}

/* 左侧导航：与主区用羽化分隔线区分 */
.dl__side {
  width: 180px;
  flex-shrink: 0;
  border-right: 1px solid var(--border);
  background: var(--bg-soft-solid);
  display: flex;
  flex-direction: column;
  padding: var(--sp-4) 0;
}
.dl__side-title {
  font-size: 11px;
  color: var(--text-4);
  padding: 0 18px 10px;
  letter-spacing: 1.2px;
  text-transform: uppercase;
}
.dl__nav {
  display: flex;
  flex-direction: column;
  gap: 2px;
  padding: 0 var(--sp-2);
}
/* 导航项：胶囊按钮，激活态用强调底 */
.dl__nav-item {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  padding: 8px 12px;
  font-size: 13px;
  color: var(--text-3);
  background: transparent;
  border: none;
  cursor: pointer;
  text-align: left;
  border-radius: var(--r-sm);
  transition: background-color var(--dur-1) var(--ease), color var(--dur-1) var(--ease);
}
.dl__nav-item:hover {
  background: var(--hover-tint);
  color: var(--text);
}
.dl__nav-item--active {
  background: var(--accent);
  color: var(--on-accent);
}
.dl__nav-item--active:hover {
  background: var(--accent);
  color: var(--on-accent);
}

.dl__main {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}
.dl__panel {
  flex: 1;
  min-height: 0;
  display: flex;
  flex-direction: column;
  overflow: hidden;
}

.dl__pane {
  padding: var(--sp-5) var(--sp-6);
  height: 100%;
  overflow-y: auto;
}
.dl__pane-header {
  margin-bottom: var(--sp-4);
  padding-bottom: var(--sp-2);
  border-bottom: 1px solid var(--border);
}
.dl__pane-title {
  font-size: 16px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 2px;
}
.dl__pane-sub {
  font-size: 12px;
  color: var(--text-4);
}

.dl__empty {
  padding: 60px 0;
  text-align: center;
  color: var(--text-4);
  font-size: 13px;
}

.dl__tasks {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
/* 任务卡：统一圆角与克制阴影 */
.dl__task {
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  background: var(--panel-solid);
  box-shadow: var(--shadow-1);
  padding: 10px 12px;
}
.dl__task-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: var(--sp-1);
}
.dl__task-id {
  font-size: 12px;
  color: var(--text-2);
}
.dl__task-status {
  font-size: 11px;
  padding: 2px 8px;
  background: var(--info-bg);
  color: var(--info-text);
  border-radius: var(--r-full);
}
.dl__task-status--downloading { background: var(--success-bg); color: var(--success-text); }
.dl__task-status--extracting  { background: var(--info-bg);    color: var(--info-text); }
.dl__task-status--completed   { background: var(--success-bg); color: var(--success-text); }
.dl__task-status--failed      { background: var(--danger-bg);  color: var(--danger-text); }
.dl__task-status--canceled    { background: var(--info-bg);    color: var(--text-4); }
.dl__task-body {
  font-size: 12px;
  color: var(--text-3);
}
.dl__task-meta {
  display: flex;
  gap: 6px;
  flex-wrap: wrap;
}

.dl__form {
  max-width: 560px;
}
.dl__form-row {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-bottom: var(--sp-3);
}
.dl__form-label {
  font-size: 12px;
  color: var(--text-3);
}
.dl__form-inline {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}
.dl__form-inline .el-input {
  flex: 1;
  min-width: 0;
}
.dl__form-inline .el-button {
  flex-shrink: 0;
}
.dl__form-action {
  margin-top: var(--sp-1);
}
.dl__form-tip {
  margin-top: 10px;
  font-size: 11px;
  line-height: 1.6;
}

.dl__limit-input {
  width: 200px;
}

/* 区块：与上方内容用分隔线拉开层次 */
.dl__block {
  margin-top: var(--sp-6);
  padding-top: 18px;
  border-top: 1px solid var(--border);
}
.dl__block-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 10px;
}
.dl__block-tip {
  font-size: 12px;
  color: var(--text-4);
  line-height: 1.6;
  margin-bottom: var(--sp-3);
}
.dl__block-row {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-3);
  margin-bottom: 10px;
}
.dl__block-label {
  flex-shrink: 0;
  width: 90px;
  font-size: 12px;
  color: var(--text-3);
  line-height: 22px;
}
.dl__block-empty {
  font-size: 12px;
  color: var(--text-4);
  line-height: 22px;
}
.dl__tags {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
}
.dl__cache-options {
  margin-bottom: var(--sp-3);
}
.cache__options {
  display: flex;
  flex-direction: column;
  gap: 6px;
  margin-top: 6px;
}
</style>
