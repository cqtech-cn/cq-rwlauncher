<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { authApi, whenReady } from '@/api/pywebview'
import AccountLogin from '@/components/AccountLogin.vue'
import AccountProfile from '@/components/AccountProfile.vue'
import BackupPanel from '@/components/BackupPanel.vue'
import SaveManager from '@/components/SaveManager.vue'

const { t } = useI18n()

/** 顶部标签分区：账号 / 备份 / 存档 */
const sections = ['account', 'backup', 'saves'] as const
const activeSection = ref<(typeof sections)[number]>('account')

/** 账号共享状态 */
const usernameText = ref('')
const loggedIn = ref(false)
const baseUrl = ref('http://server.cqfishnet.cn:48117')
const reachable = ref(false)
const serviceVersion = ref('')

const refresh = async () => {
  const st = await authApi.status()
  baseUrl.value = st.base_url || 'http://server.cqfishnet.cn:48117'
  usernameText.value = st.username || ''
  loggedIn.value = !!st.username
  const h = await authApi.health()
  reachable.value = !!h.reachable
  serviceVersion.value = h.version || ''
  if (loggedIn.value) {
    const me = await authApi.me()
    if (!me.ok && me.error) {
      await authApi.logout()
      loggedIn.value = false
      usernameText.value = ''
      ElMessage.warning(t('account.msg.expired'))
    }
  }
}

/** 手动重新检测账号服务（提示条上的按钮） */
const probing = ref(false)
const onRecheck = async () => {
  probing.value = true
  try {
    await refresh()
  } finally {
    probing.value = false
  }
}

const onLoginSuccess = async () => {
  await refresh()
  activeSection.value = 'backup'
}

const onLogout = async () => {
  await authApi.logout()
  usernameText.value = ''
  loggedIn.value = false
  ElMessage.success(t('account.msg.loggedOut'))
  await refresh()
}

onMounted(async () => {
  await whenReady()
  await refresh()
})
</script>

<template>
  <div class="account">
    <div class="account__head">
      <div>
        <div class="account__title">{{ t('account.title') }}</div>
        <div class="account__sub">{{ t('account.subtitle') }}</div>
      </div>
      <div class="account__badges">
        <span
          :class="['account__badge', reachable ? 'account__badge--ok' : 'account__badge--off']"
        >
          {{ reachable ? t('account.online') : t('account.offline') }}
        </span>
        <span v-if="reachable && serviceVersion" class="account__badge account__badge--info">
          v{{ serviceVersion }}
        </span>
      </div>
    </div>

    <!-- 账号服务不可用：醒目提示（平台渠道受影响，模组仍可走铁锈盒子渠道） -->
    <div v-if="!reachable" class="account__alert">
      <span class="account__alert-icon" aria-hidden="true">
        <svg viewBox="0 0 16 16" width="16" height="16">
          <path d="M8 1.6 15.2 14H0.8L8 1.6Z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>
          <path d="M8 6.2v3.6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
          <circle cx="8" cy="12" r="0.85" fill="currentColor"/>
        </svg>
      </span>
      <div class="account__alert-body">
        <div class="account__alert-title">{{ t('account.offlineTitle') }}</div>
        <div class="account__alert-msg">{{ t('account.offlineWarn', { url: baseUrl }) }}</div>
      </div>
      <button class="account__alert-btn" :disabled="probing" @click="onRecheck">
        {{ probing ? t('app.accountAlert.checking') : t('account.recheck') }}
      </button>
    </div>

    <div class="account__notice">
      <span class="account__notice-tag">{{ t('account.noticeTag') }}</span>
      {{ t('account.notice') }}
    </div>

    <!-- 顶部胶囊标签页：账号 / 备份 / 存档 -->
    <div class="account__tabs" role="tablist">
      <button
        v-for="s in sections"
        :key="s"
        role="tab"
        :aria-selected="activeSection === s"
        class="account__tab"
        :class="{ 'is-active': activeSection === s }"
        @click="activeSection = s"
      >
        {{ t(`account.side.${s}`) }}
      </button>
    </div>

    <div class="account__body">
      <div class="account__main">
        <!-- 账号：登录 / 注册 / 用户信息（居中窄卡片） -->
        <div v-show="activeSection === 'account'" class="account__panel account__panel--center">
          <AccountProfile v-if="loggedIn" :username="usernameText" @logout="onLogout" />
          <AccountLogin
            v-else
            :base-url="baseUrl"
            :reachable="reachable"
            @success="onLoginSuccess"
          />
        </div>

        <!-- 备份：玩家数据云备份（加宽卡片） -->
        <div v-show="activeSection === 'backup'" class="account__panel account__panel--wide">
          <BackupPanel v-if="loggedIn" />
          <div v-else class="account__empty">
            {{ t('account.backupLoginHint') }}
          </div>
        </div>

        <!-- 存档：存档管理（加宽卡片） -->
        <div v-show="activeSection === 'saves'" class="account__panel account__panel--wide">
          <SaveManager />
        </div>
      </div>
    </div>
  </div>
</template>

<style scoped>
/* 页面容器：单列居中 */
.account {
  height: 100%;
  display: flex;
  flex-direction: column;
  padding: var(--sp-6) var(--sp-8);
  margin: 0 auto;
  max-width: 1120px;
  min-height: 0;
}

.account__head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  margin-bottom: var(--sp-5);
  flex-shrink: 0;
}

.account__title {
  font-size: 18px;
  font-weight: 600;
  letter-spacing: 0.2px;
}

.account__sub {
  margin-top: 4px;
  font-size: 12px;
  color: var(--text-3);
}

.account__badges {
  display: flex;
  gap: var(--sp-2);
}

/* 状态徽标：胶囊形态 */
.account__badge {
  font-size: 11px;
  font-weight: 600;
  padding: 3px 10px;
  border-radius: var(--r-full);
  background: var(--info-bg);
  color: var(--info-text);
}

.account__badge--ok {
  color: var(--success-text);
  background: var(--success-bg);
}

.account__badge--off {
  color: var(--danger-text);
  background: var(--danger-bg);
  border: 1px solid var(--danger-text);
}

.account__badge--info {
  color: var(--text-4);
}

/* 账号服务不可用：醒目提示条 */
.account__alert {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-shrink: 0;
  margin-bottom: var(--sp-3);
  padding: 12px 14px;
  color: var(--danger-text);
  background: var(--danger-bg);
  border-radius: var(--r-md);
  border: 1px solid var(--danger-text);
  border-left-width: 4px;
}
.account__alert-icon {
  display: inline-flex;
  flex-shrink: 0;
}
.account__alert-body {
  flex: 1;
  min-width: 0;
}
.account__alert-title {
  font-size: 13.5px;
  font-weight: 700;
}
.account__alert-msg {
  margin-top: 3px;
  font-size: 12px;
  line-height: 1.6;
  overflow-wrap: anywhere;
}
.account__alert-btn {
  flex-shrink: 0;
  padding: 6px 14px;
  font-size: 12px;
  font-weight: 600;
  background: transparent;
  color: inherit;
  border: 1px solid currentColor;
  border-radius: var(--r-full);
  transition: background-color var(--dur-1) var(--ease);
}
.account__alert-btn:hover:not(:disabled) {
  background: color-mix(in srgb, currentColor 14%, transparent);
}
.account__alert-btn:disabled {
  opacity: 0.55;
  cursor: default;
}

/* 说明条：统一使用警示语义色 */
.account__notice {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  margin-bottom: var(--sp-5);
  padding: 10px 14px;
  border-radius: var(--r-sm);
  font-size: 12px;
  line-height: 1.65;
  color: var(--warn-text);
  background: var(--warn-bg);
  border-left: 3px solid currentColor;
  flex-shrink: 0;
}

.account__notice-tag {
  flex-shrink: 0;
  font-size: 11px;
  font-weight: 600;
  padding: 1px 9px;
  border-radius: var(--r-full);
  color: inherit;
  background: color-mix(in srgb, currentColor 14%, transparent);
  border: 1px solid color-mix(in srgb, currentColor 40%, transparent);
}

/* 顶部胶囊标签页：居中分段控件 */
.account__tabs {
  flex-shrink: 0;
  align-self: center;
  display: inline-flex;
  gap: 4px;
  padding: 4px;
  margin-bottom: var(--sp-5);
  background: var(--panel-solid);
  border: 1px solid var(--border);
  border-radius: var(--r-full);
}

.account__tab {
  padding: 7px 22px;
  font-size: 13px;
  color: var(--text-3);
  background: transparent;
  border: 1px solid transparent;
  border-radius: var(--r-full);
  cursor: pointer;
  outline: none;
  transition: background-color var(--dur-1) var(--ease), color var(--dur-1) var(--ease),
    border-color var(--dur-1) var(--ease);
}

.account__tab:hover {
  color: var(--text);
  background: var(--hover-tint);
}

.account__tab.is-active {
  color: var(--text);
  font-weight: 600;
  background: var(--selected-tint);
  border-color: color-mix(in srgb, var(--accent) 36%, transparent);
}

.account__tab:active {
  background: var(--press-tint);
}

/* 主体：标签页下方的单内容区，自身承担纵向滚动 */
.account__body {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
}

.account__main {
  width: 100%;
  display: flex;
  flex-direction: column;
  padding-bottom: var(--sp-4);
}

.account__panel {
  width: 100%;
  margin-inline: auto;
  background: var(--panel-solid);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-1);
  padding: var(--sp-6);
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

/* 登录 / 注册 / 用户信息：居中窄卡片 */
.account__panel--center {
  max-width: 440px;
}

/* 备份 / 存档：加宽卡片 */
.account__panel--wide {
  max-width: 940px;
}

.account__empty {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-4);
  padding: var(--sp-2) 0;
}
</style>
