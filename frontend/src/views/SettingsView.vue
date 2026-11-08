<script setup lang="ts">
import { onMounted, onUnmounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { appApi, authApi, configApi, javaApi, windowApi, whenReady } from '@/api/pywebview'
import { applyAppearance, sanitizeAppearance, setBackground, clearBackground, type AppearanceState } from '@/stores/appearance'
import { applyFestivalFromConfig } from '@/stores/festival'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const cfg = ref<any>({})
const saving = ref(false)
const appearanceForm = ref<AppearanceState>(sanitizeAppearance(undefined))

/** Java 版（简体中文增强版）运行环境表单 + 实时状态 */
const javaForm = ref<{ mode: 'auto' | 'java' | 'exe'; auto_download: boolean; feature_version: number }>({
  mode: 'auto',
  auto_download: true,
  feature_version: 21,
})
const javaState = ref<{
  has_jar: boolean
  needs_install: boolean
  installing: boolean
  java_path: string | null
  java_major: number | null
  java_source: string
  reason: string
}>({
  has_jar: false,
  needs_install: true,
  installing: false,
  java_path: null,
  java_major: null,
  java_source: 'none',
  reason: '',
})

function javaSourceLabel(): string {
  const s = javaState.value.java_source
  if (s === 'bundled64') return t('settings.java.sourceBundled64')
  if (s === 'bundled32') return t('settings.java.sourceBundled32')
  if (s === 'system') return t('settings.java.sourceSystem')
  return t('settings.java.sourceNone')
}

const refreshJavaState = async () => {
  try {
    javaState.value = await javaApi.status()
  } catch {
    // 开发 / 浏览器调试模式无 pywebview：保持初始占位
  }
}

const onInstallJre = async () => {
  try {
    const res = await javaApi.installRuntime()
    if (res?.already) {
      ElMessage.success(t('settings.java.installAlready'))
    } else if (res?.installing) {
      ElMessage.success(t('settings.java.installStarting'))
    } else {
      ElMessage.error(res?.error || t('settings.java.installFailed'))
    }
  } catch (e: any) {
    ElMessage.error(t('settings.java.installFailedErr', { err: e?.message || t('common.unknownError') }))
  } finally {
    await refreshJavaState()
  }
}

/** 账号服务（服务连接配置） */
const accountCfg = ref({ base_url: 'http://server.cqfishnet.cn:48117', timeout: 5 })
const accountState = ref({ reachable: false, version: '', username: '' })
const savingAccount = ref(false)

// 构建日期由 vite.config.ts 在构建时注入，用于核对前端版本
const buildDate = __BUILD_DATE__
const appVersion = ref('')

/** 左侧边栏分组：下载源/限速/清除缓存/已安装资源已移至「下载」页，
 *  存档管理已移至「账号」页，故障诊断已移至「服务」页 */
const sections = [
  { id: 'path' },
  { id: 'appearance' },
  { id: 'close' },
  { id: 'java' },
  { id: 'account' },
]
const activeSection = ref('path')

/** 外部（如告警弹窗）请求跳转到本页指定分区 */
const onOpenSection = (e: Event) => {
  const id = (e as CustomEvent<string>).detail
  if (id && sections.some((s) => s.id === id)) {
    activeSection.value = id
  }
}

/** 节日特别主题：开 / 关（关掉后不再应用任何节日点缀配色） */
const festivalForm = ref({ enabled: true })
const onFestivalToggle = () => {
  applyFestivalFromConfig(festivalForm.value.enabled)
}

const load = async () => {
  cfg.value = await configApi.get()
  festivalForm.value = { enabled: cfg.value.festival_theme?.enabled !== false }
  appearanceForm.value = sanitizeAppearance(cfg.value.appearance)
  // Java 运行环境表单与状态（老配置可能缺默认子键，做一次兜底）
  const jr = cfg.value.java_runtime || {}
  javaForm.value = {
    mode: jr.mode || 'auto',
    auto_download: jr.auto_download !== false,
    feature_version: jr.feature_version || 21,
  }
  await refreshJavaState()
  try {
    const info = await appApi.info()
    if (info?.version) appVersion.value = info.version
  } catch {
    // 浏览器开发模式：保持空
  }
  try {
    const st = await authApi.status()
    accountCfg.value.base_url = st.base_url || 'http://server.cqfishnet.cn:48117'
    accountCfg.value.timeout = st.timeout || 5
    accountState.value.username = st.username || ''
    const h = await authApi.health()
    accountState.value.reachable = !!h.reachable
    accountState.value.version = h.version || ''
  } catch {
    // 服务离线：保持默认值
  }
}

/** 保存账号服务配置（独立于下方统一保存） */
const onSaveAccount = async () => {
  savingAccount.value = true
  try {
    const res = await authApi.setConfig({
      base_url: accountCfg.value.base_url.trim(),
      timeout: Number(accountCfg.value.timeout) || 5,
    })
    if (res.ok) {
      await load()
      ElMessage.success(t('settings.account.saved'))
    } else {
      ElMessage.error(t('settings.account.saveFailed'))
    }
  } finally {
    savingAccount.value = false
  }
}

/** 外观控件变化：即时预览（不落盘） */
const previewAppearance = () => {
  applyAppearance(appearanceForm.value)
}

const onSave = async () => {
  saving.value = true
  try {
    await configApi.update({
      game_install_path: cfg.value.game_install_path,
      game_exe_name: cfg.value.game_exe_name,
      close_behavior: cfg.value.close_behavior,
      appearance: sanitizeAppearance(appearanceForm.value),
      java_runtime: javaForm.value,
      festival_theme: {
        ...(cfg.value.festival_theme || {}),
        enabled: festivalForm.value.enabled,
      },
    })
    // 持久化后再次同步外观状态
    applyAppearance(appearanceForm.value)
    ElMessage.success(t('settings.saved'))
    await load()
  } catch (e: any) {
    ElMessage.error(t('settings.saveFailed', { err: e?.message || t('common.unknownError') }))
  } finally {
    saving.value = false
  }
}

const onResetCloseBehavior = async () => {
  await configApi.update({ close_behavior: 'ask' })
  await load()
  ElMessage.success(t('settings.close.resetOk'))
}

const onPickBackground = async () => {
  try {
    const res = await windowApi.pickBackgroundImage()
    if (res?.ok && res.path) {
      appearanceForm.value.background_image = res.path
      setBackground(res.path, res.data_uri || '')
      ElMessage.success(t('settings.appearance.bgChanged'))
    } else if (res?.error) {
      ElMessage.error(res.error)
    }
  } catch {
    ElMessage.info(t('settings.appearance.browserMode'))
  }
}

const onClearBackground = () => {
  appearanceForm.value.background_image = ''
  clearBackground()
}

onMounted(async () => {
  await whenReady()
  await load()
  window.addEventListener('rw:open:settings-section', onOpenSection)
})

onUnmounted(() => {
  window.removeEventListener('rw:open:settings-section', onOpenSection)
})
</script>

<template>
  <div class="settings">
    <aside class="settings__side">
      <div
        v-for="s in sections"
        :key="s.id"
        class="settings__menu-item"
        :class="{ 'is-active': activeSection === s.id }"
        @click="activeSection = s.id"
      >
        {{ t(`settings.side.${s.id}`) }}
      </div>
    </aside>

    <div class="settings__main">
      <!-- 版本信息：方便核对当前构建 -->
      <div class="settings__meta">
        <span v-if="appVersion" class="settings__meta-item">
          <span class="settings__meta-label">{{ t('settings.version') }}</span>
          <span class="settings__meta-value text-mono">v{{ appVersion }}</span>
        </span>
        <span class="settings__meta-item">
          <span class="settings__meta-label">{{ t('settings.buildDate') }}</span>
          <span class="settings__meta-value text-mono">{{ buildDate }}</span>
        </span>
      </div>

      <!-- 路径设置 -->
      <div v-show="activeSection === 'path'" class="settings__panel">
        <div class="settings__title">{{ t('settings.path.title') }}</div>

        <div class="settings__row">
          <label class="settings__label">{{ t('settings.path.installDir') }}</label>
          <el-input v-model="cfg.game_install_path" placeholder="D:\RustedWarfare" />
        </div>

        <div class="settings__row">
          <label class="settings__label">{{ t('settings.path.exeName') }}</label>
          <el-input v-model="cfg.game_exe_name" placeholder="RustedWarfare.exe" />
        </div>
      </div>

      <!-- 外观 -->
      <div v-show="activeSection === 'appearance'" class="settings__panel">
        <div class="settings__title">{{ t('settings.appearance.title') }}</div>
        <div class="settings__hint-block">{{ t('settings.appearance.hint') }}</div>

        <div class="settings__row">
          <label class="settings__label">{{ t('settings.appearance.theme') }}</label>
          <el-radio-group v-model="appearanceForm.theme" @change="previewAppearance">
            <el-radio value="light">{{ t('settings.appearance.themeLight') }}</el-radio>
            <el-radio value="dark">{{ t('settings.appearance.themeDark') }}</el-radio>
            <el-radio value="mizuiro">{{ t('settings.appearance.themeMizuiro') }}</el-radio>
          </el-radio-group>
        </div>

        <div class="settings__row">
          <label class="settings__label">{{ t('settings.appearance.density') }}</label>
          <el-radio-group v-model="appearanceForm.density" @change="previewAppearance">
            <el-radio value="comfortable">{{ t('settings.appearance.densityComfortable') }}</el-radio>
            <el-radio value="compact">{{ t('settings.appearance.densityCompact') }}</el-radio>
          </el-radio-group>
        </div>

        <div class="settings__row">
          <label class="settings__label">{{ t('settings.appearance.opacity') }}</label>
          <div class="appearance__opacity">
            <el-slider
              v-model="appearanceForm.panel_opacity"
              :min="0"
              :max="100"
              :step="5"
              class="appearance__slider"
              @change="previewAppearance"
            />
            <span class="appearance__opacity-value">{{ appearanceForm.panel_opacity }}%</span>
          </div>
        </div>

        <div class="settings__row settings__row--top">
          <label class="settings__label">{{ t('settings.appearance.background') }}</label>
          <div class="appearance__bg">
            <div v-if="appearanceForm.background_image" class="appearance__bg-path text-mono">
              {{ appearanceForm.background_image }}
            </div>
            <div v-else class="text-faint">{{ t('settings.appearance.bgNotSet') }}</div>
            <div class="appearance__bg-actions">
              <el-button size="small" @click="onPickBackground">{{ t('settings.appearance.pickBg') }}</el-button>
              <el-button
                v-if="appearanceForm.background_image"
                size="small"
                @click="onClearBackground"
              >{{ t('settings.appearance.removeBg') }}</el-button>
            </div>
          </div>
        </div>

        <div class="settings__row">
          <label class="settings__label">{{ t('settings.appearance.homeModules') }}</label>
          <div class="appearance__modules">
            <div class="appearance__module">
              <span>{{ t('settings.appearance.moduleLaunch') }}</span>
              <el-switch
                v-model="appearanceForm.home_modules.launch"
                @change="previewAppearance"
              />
            </div>
            <div class="appearance__module">
              <span>{{ t('settings.appearance.moduleDownload') }}</span>
              <el-switch
                v-model="appearanceForm.home_modules.download"
                @change="previewAppearance"
              />
            </div>
          </div>
        </div>

        <div class="settings__row settings__row--top">
          <label class="settings__label">{{ t('settings.appearance.festival') }}</label>
          <div class="appearance__festival">
            <el-switch v-model="festivalForm.enabled" @change="onFestivalToggle" />
            <div class="appearance__festival-hint">{{ t('settings.appearance.festivalHint') }}</div>
          </div>
        </div>
      </div>

      <!-- 关闭行为 -->
      <div v-show="activeSection === 'close'" class="settings__panel">
        <div class="settings__title">{{ t('settings.close.title') }}</div>

        <div class="settings__row">
          <label class="settings__label">{{ t('settings.close.label') }}</label>
          <el-radio-group v-model="cfg.close_behavior">
            <el-radio :value="'minimize'">{{ t('settings.close.minimize') }}</el-radio>
            <el-radio :value="'exit'">{{ t('settings.close.exit') }}</el-radio>
            <el-radio value="ask">{{ t('settings.close.ask') }}</el-radio>
          </el-radio-group>
        </div>

        <el-button size="small" @click="onResetCloseBehavior">{{ t('settings.close.reset') }}</el-button>
      </div>

      <!-- Java 版运行环境 -->
      <div v-show="activeSection === 'java'" class="settings__panel">
        <div class="settings__title">{{ t('settings.java.title') }}</div>
        <div class="settings__hint-block">{{ t('settings.java.hint') }}</div>

        <div class="settings__row settings__row--top">
          <label class="settings__label">{{ t('settings.java.mode') }}</label>
          <el-radio-group v-model="javaForm.mode">
            <el-radio value="auto">{{ t('settings.java.modeAuto') }}</el-radio>
            <el-radio value="java">{{ t('settings.java.modeJava') }}</el-radio>
            <el-radio value="exe">{{ t('settings.java.modeExe') }}</el-radio>
          </el-radio-group>
        </div>

        <div class="settings__row settings__row--top">
          <label class="settings__label">{{ t('settings.java.autoDownload') }}</label>
          <el-switch v-model="javaForm.auto_download" />
        </div>

        <div class="settings__row">
          <label class="settings__label">{{ t('settings.java.featureVersion') }}</label>
          <el-input-number v-model="javaForm.feature_version" :min="9" :max="64" />
        </div>

        <div class="settings__row settings__row--top">
          <label class="settings__label">{{ t('settings.java.status') }}</label>
          <div class="java__state">
            <span
              v-if="!javaState.has_jar"
              class="java__state-line text-faint"
            >{{ t('settings.java.stateNoJar') }}</span>
            <span
              v-else-if="javaState.installing"
              class="java__state-line"
            >{{ t('settings.java.stateInstalling') }}</span>
            <span
              v-else-if="javaState.needs_install"
              class="java__state-line java__state-line--warn"
            >{{ t('settings.java.stateMissing') }}</span>
            <span v-else class="java__state-line java__state-line--ok">
              {{ t('settings.java.stateReady', {
                major: javaState.java_major ?? '',
                source: javaSourceLabel(),
                path: javaState.java_path || '',
              }) }}
            </span>
            <span v-if="javaState.reason" class="text-faint">{{ javaState.reason }}</span>
            <div class="java__actions">
              <el-button
                size="small"
                type="primary"
                :loading="javaState.installing"
                :disabled="!javaState.has_jar || javaState.installing"
                @click="onInstallJre"
              >{{ t('settings.java.installBtn') }}</el-button>
              <el-button size="small" :disabled="javaState.installing" @click="refreshJavaState">
                {{ t('settings.java.refresh') }}
              </el-button>
            </div>
          </div>
        </div>
      </div>

      <!-- 账号服务 -->
      <div v-show="activeSection === 'account'" class="settings__panel settings__panel--account">
        <div class="settings__title">{{ t('settings.account.title') }}</div>
        <div class="settings__hint-block">{{ t('settings.account.hint') }}</div>

        <div class="settings__row">
          <label class="settings__label">{{ t('settings.account.url') }}</label>
          <el-input v-model="accountCfg.base_url" placeholder="http://server.cqfishnet.cn:48117" />
        </div>

        <div class="settings__row">
          <label class="settings__label">{{ t('settings.account.timeout') }}</label>
          <el-input-number v-model="accountCfg.timeout" :min="1" :max="60" />
        </div>

        <div class="settings__row">
          <label class="settings__label">{{ t('settings.account.status') }}</label>
          <div class="settings__account-status">
            <span v-if="accountState.reachable" class="ui-badge ui-badge--success">
              {{ t('settings.account.connected', { version: accountState.version }) }}
            </span>
            <span v-else class="ui-badge ui-badge--danger">
              {{ t('settings.account.offline') }}
            </span>
            <span v-if="accountState.username" class="ui-badge ui-badge--success">
              {{ t('settings.account.loggedIn', { name: accountState.username }) }}
            </span>
          </div>
        </div>

        <div v-if="!accountState.reachable" class="ui-notice ui-notice--danger settings__account-alert">
          <span class="ui-notice__icon" aria-hidden="true">
            <svg viewBox="0 0 16 16" width="14" height="14">
              <path d="M8 1.6 15.2 14H0.8L8 1.6Z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>
              <path d="M8 6.2v3.6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
              <circle cx="8" cy="12" r="0.85" fill="currentColor"/>
            </svg>
          </span>
          <span class="ui-notice__body">{{ t('account.offlineWarn', { url: accountCfg.base_url }) }}</span>
        </div>

        <div class="settings__row">
          <label class="settings__label" />
          <el-button size="small" type="primary" :loading="savingAccount" @click="onSaveAccount">
            {{ t('settings.account.save') }}
          </el-button>
        </div>
      </div>

      <div class="settings__action">
        <el-button type="primary" :loading="saving" @click="onSave">{{ t('settings.saveBtn') }}</el-button>
      </div>
    </div>
  </div>
</template>

<style scoped>
.settings {
  height: 100%;
  display: flex;
  gap: var(--gap);
  padding: var(--pad);
  overflow: hidden;
}

/* 左侧分区菜单 */
.settings__side {
  width: 150px;
  flex-shrink: 0;
  align-self: flex-start;
  background: var(--panel-solid);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-1);
  padding: var(--sp-2);
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.settings__menu-item {
  position: relative;
  padding: 9px 12px;
  font-size: 12px;
  color: var(--text-2);
  border-radius: var(--r-sm);
  cursor: pointer;
  user-select: none;
  transition: background-color var(--dur-1) var(--ease), color var(--dur-1) var(--ease);
}
.settings__menu-item::before {
  content: "";
  position: absolute;
  left: 0;
  top: 50%;
  width: 3px;
  height: 0;
  border-radius: var(--r-full);
  background: var(--accent);
  transform: translateY(-50%);
  transition: height var(--dur-2) var(--ease);
}
.settings__menu-item:hover {
  background: var(--hover-tint);
  color: var(--text);
}
.settings__menu-item.is-active {
  background: var(--selected-tint);
  color: var(--accent);
  font-weight: 600;
}
.settings__menu-item.is-active::before {
  height: 16px;
}

/* 右侧内容区 */
.settings__main {
  flex: 1;
  min-width: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: var(--gap);
  padding-bottom: var(--sp-2);
  max-width: 860px;
  margin: 0 auto;
}

.settings__panel {
  background: var(--panel-solid);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-1);
  padding: var(--sp-5) var(--sp-6);
  display: flex;
  flex-direction: column;
  gap: var(--sp-4);
}

.settings__title {
  position: relative;
  font-size: 15px;
  font-weight: 600;
  letter-spacing: 0.2px;
  color: var(--text);
  padding-bottom: var(--sp-2);
}
.settings__title::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 1px;
  background: linear-gradient(90deg, var(--border), transparent);
}

/* 顶部版本信息条：始终可见，方便核对构建日期 */
.settings__meta {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: var(--sp-2) var(--sp-5);
  padding: 0 2px;
}
.settings__meta-item {
  display: inline-flex;
  align-items: center;
  gap: var(--sp-2);
  font-size: 12px;
}
.settings__meta-label {
  color: var(--text-3);
}
.settings__meta-value {
  color: var(--text);
  font-weight: 600;
}

.settings__row {
  display: flex;
  align-items: center;
  gap: var(--sp-4);
}

.settings__row--top {
  align-items: flex-start;
}

.settings__label {
  width: 140px;
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.6;
  padding-top: 8px;
}

.settings__hint-block {
  font-size: 12px;
  color: var(--text-4);
  line-height: 1.6;
}

.settings__action {
  display: flex;
  justify-content: flex-end;
  margin-top: var(--sp-1);
}

/* 外观面板 */
.appearance__opacity {
  flex: 1;
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  min-width: 0;
}
.appearance__slider {
  flex: 1;
  max-width: 320px;
}
.appearance__opacity-value {
  font-size: 12px;
  color: var(--text-3);
  width: 42px;
  flex-shrink: 0;
}

.appearance__bg {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.appearance__bg-path {
  font-size: 11px;
  color: var(--text-3);
  word-break: break-all;
  line-height: 1.5;
}
.appearance__bg-actions {
  display: flex;
  gap: var(--sp-2);
}

.appearance__modules {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}
.appearance__module {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  font-size: 12px;
  color: var(--text-2);
}

/* 节日特别主题开关 */
.appearance__festival {
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  max-width: 460px;
}
.appearance__festival-hint {
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-4);
}

/* 账号服务面板 */
.settings__panel--account .el-input {
  max-width: 360px;
}
.settings__panel--account .el-input-number {
  max-width: 160px;
}
.settings__account-status {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  flex-wrap: wrap;
}

/* 账号服务不可用：设置页内醒目提示 */
.settings__account-alert {
  margin: var(--sp-3) 0 var(--sp-1);
}

/* Java 运行环境面板 */
.settings__panel .java__state {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.java__state-line {
  font-size: 12px;
  line-height: 1.6;
  color: var(--text-2);
  white-space: pre-line;
  word-break: break-all;
}
.java__state-line--warn {
  color: var(--warn-text);
}
.java__state-line--ok {
  color: var(--success-text);
}
.java__actions {
  display: flex;
  gap: var(--sp-2);
  margin-top: var(--sp-1);
}
</style>