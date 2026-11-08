<script setup lang="ts">
/**
 * 服务页：分享我的模组 + 同步他人模组 + RW-HPS 房间列表。
 * 分享码把本机已下载的模组 / 地图打包成 6 位码，好友凭码一键同步；
 * 房间数据来自配套服务（RW-HPS 集成），房间可绑定分享码。
 */
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import {
  resourceApi,
  roomApi,
  shareCodeApi,
  whenReady,
  type RoomItem,
  type ProfileMod,
} from '@/api/pywebview'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const loading = ref(false)
const rooms = ref<RoomItem[]>([])
const configured = ref(true)
const lastError = ref('')
const shareInput = ref('')
const syncingRoom = ref('')
const localMods = ref<ProfileMod[]>([])
const shareLoading = ref(false)
const shareCodeText = ref('')
const shareExpiresAt = ref('')

/** 拉取本机已下载的模组 / 地图清单 */
const loadLocal = async () => {
  try {
    const r = await resourceApi.localInstalled()
    if (r.ok) localMods.value = r.items || []
  } catch {
    // 本地清单获取失败不打断页面
  }
}

/** 把本机已下载的模组 / 地图打包成 6 位分享码 */
const createShareCode = async () => {
  if (!localMods.value.length) {
    ElMessage.warning(t('service.shareEmpty'))
    return
  }
  shareLoading.value = true
  try {
    const r = await shareCodeApi.create(localMods.value)
    if (r.ok && r.code) {
      shareCodeText.value = r.code
      shareExpiresAt.value = r.expires_at || ''
      ElMessage.success(t('service.shareDone'))
    } else {
      ElMessage.error(r.error || t('service.shareFailed'))
    }
  } catch (e: any) {
    ElMessage.error(e?.message || t('service.shareFailed'))
  } finally {
    shareLoading.value = false
  }
}

/** 复制分享码到剪贴板 */
const copyShareCode = async () => {
  try {
    await navigator.clipboard.writeText(shareCodeText.value)
    ElMessage.success(t('service.codeCopied'))
  } catch {
    // 剪贴板不可用时静默
  }
}

const load = async () => {
  loading.value = true
  lastError.value = ''
  try {
    const r = await roomApi.list('open')
    if (r.ok) {
      rooms.value = r.items || []
      configured.value = !!r.rwhps_configured
    } else {
      lastError.value = r.error || t('room.fetchFailed')
      rooms.value = []
    }
  } catch (e: any) {
    lastError.value = e?.message || t('room.fetchFailed')
    rooms.value = []
  } finally {
    loading.value = false
  }
}

const syncFromCode = async () => {
  const code = shareInput.value.trim().toUpperCase()
  if (code.length !== 6) {
    ElMessage.warning(t('room.codeFormat'))
    return
  }
  const r = await shareCodeApi.resolve(code)
  if (!r.ok) {
    ElMessage.error(r.error || t('room.resolveFailed'))
    return
  }
  const mods = r.mods || []
  if (!mods.length) {
    ElMessage.warning(t('room.noMods'))
    return
  }
  try {
    await ElMessageBox.confirm(
      mods.map((m, i) => `${i + 1}. ${m.title}（${m.kind}）`).join('\n'),
      t('room.codeResolved', { code, count: mods.length }),
      {
        confirmButtonText: t('room.downloadAll'),
        cancelButtonText: t('room.cancel'),
        customStyle: { whiteSpace: 'pre-line', maxHeight: '70vh', overflowY: 'auto' },
      },
    )
  } catch {
    return
  }
  let okCount = 0
  for (const m of mods) {
    try {
      const d = await resourceApi.download(m.kind, m.title, m.url)
      if (d.ok) okCount += 1
    } catch {
      // 单条失败不中断
    }
  }
  ElMessage.success(t('room.syncStarted', { count: okCount }))
}

const syncRoom = async (room: RoomItem) => {
  if (syncingRoom.value) return
  syncingRoom.value = room.room_id
  try {
    const r = await roomApi.syncMods(room.room_id)
    if (r.ok) {
      ElMessage.success(t('room.syncStarted', { count: r.queued }))
    } else {
      ElMessage.error(r.error || t('room.syncFailed'))
    }
  } catch (e: any) {
    ElMessage.error(e?.message || t('room.syncFailed'))
  } finally {
    syncingRoom.value = ''
  }
}

const bindCode = async (room: RoomItem) => {
  try {
    const { value } = await ElMessageBox.prompt(
      t('room.bindPrompt'),
      t('room.bindTitle'),
      {
        inputPattern: /^[A-Za-z0-9]{6}$/,
        inputErrorMessage: t('room.codeFormat'),
        inputValue: room.share_code || '',
        confirmButtonText: t('room.bindOk'),
        cancelButtonText: t('room.cancel'),
      },
    )
    const r = await roomApi.bindShare(room.room_id, value.trim().toUpperCase())
    if (r.ok) {
      ElMessage.success(t('room.bindDone'))
      await load()
    } else {
      ElMessage.error(r.error || t('room.bindFailed'))
    }
  } catch {
    // 用户取消
  }
}

onMounted(async () => {
  await whenReady()
  await load()
  await loadLocal()
})
</script>

<template>
  <div class="room">
    <header class="room__header">
      <h1 class="room__title">{{ t('service.title') }}</h1>
      <div class="room__subtitle">{{ t('service.subtitle') }}</div>
    </header>

    <div class="room__panels">
      <section class="room__panel">
        <h2 class="room__panel-title">{{ t('service.shareTitle') }}</h2>
        <p class="room__panel-desc">{{ t('service.shareDesc') }}</p>
        <div class="room__share-row">
          <span class="room__share-count">{{ t('service.shareCount', { count: localMods.length }) }}</span>
          <button
            class="room__btn room__btn--primary"
            :disabled="shareLoading || !localMods.length"
            @click="createShareCode"
          >
            {{ shareLoading ? t('service.shareGenerating') : t('service.shareBtn') }}
          </button>
        </div>
        <div v-if="shareCodeText" class="room__codebox">
          <span class="room__codebox-label">{{ t('service.codeLabel') }}</span>
          <span class="room__codebox-value">{{ shareCodeText }}</span>
          <span v-if="shareExpiresAt" class="room__codebox-expire">{{ shareExpiresAt }}</span>
          <button class="room__btn" @click="copyShareCode">{{ t('service.copy') }}</button>
        </div>
      </section>

      <section class="room__panel">
        <h2 class="room__panel-title">{{ t('service.syncTitle') }}</h2>
        <p class="room__panel-desc">{{ t('service.syncDesc') }}</p>
        <div class="room__share">
          <input
            v-model="shareInput"
            class="room__input"
            maxlength="6"
            :placeholder="t('room.codePlaceholder')"
            @keyup.enter="syncFromCode"
          >
          <button class="room__btn room__btn--primary" @click="syncFromCode">
            {{ t('room.syncFromCode') }}
          </button>
        </div>
      </section>
    </div>

    <div v-if="lastError" class="room__error">{{ lastError }}</div>
    <div v-if="!configured" class="room__hint">{{ t('room.notConfigured') }}</div>

    <section class="room__rooms">
      <div class="room__rooms-head">
        <h2 class="room__panel-title">{{ t('service.roomTitle') }}</h2>
        <button class="room__btn" :disabled="loading" @click="load">
          {{ t('room.refresh') }}
        </button>
      </div>
      <div class="room__list">
        <div v-for="r in rooms" :key="r.room_id" class="room__card">
          <div class="room__head">
            <span class="room__name">{{ r.name }}</span>
            <span class="room__count">{{ r.players }}/{{ r.max_players }}</span>
          </div>
          <div class="room__meta">
            <span v-if="r.host">{{ t('room.host') }}{{ r.host }}</span>
            <span v-if="r.map">{{ t('room.map') }}{{ r.map }}</span>
            <span v-if="r.mode">{{ t('room.mode') }}{{ r.mode }}</span>
            <span v-if="r.version">{{ t('room.version') }}{{ r.version }}</span>
          </div>
          <div class="room__foot">
            <span class="room__code" :class="{ 'room__code--empty': !r.share_code }">
              {{ r.share_code ? `${t('room.code')} ${r.share_code}` : t('room.noCode') }}
            </span>
            <div class="room__actions">
              <button class="room__btn" @click="bindCode(r)">
                {{ t('room.bind') }}
              </button>
              <button
                class="room__btn room__btn--primary"
                :disabled="!r.share_code || syncingRoom === r.room_id"
                @click="syncRoom(r)"
              >
                {{ syncingRoom === r.room_id ? t('room.syncing') : t('room.syncMods') }}
              </button>
            </div>
          </div>
        </div>
        <div v-if="!loading && !rooms.length" class="room__empty">{{ t('room.empty') }}</div>
      </div>
    </section>
  </div>
</template>

<style scoped>
.room {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  padding: var(--sp-4);
  overflow-y: auto;
}

.room__header {
  margin-bottom: 14px;
  flex-shrink: 0;
}

.room__title {
  font-size: 18px;
  font-weight: 600;
  color: var(--text);
  margin: 0 0 var(--sp-1);
}

.room__subtitle {
  font-size: 12px;
  color: var(--text-3);
}

.room__panels {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(320px, 1fr));
  gap: var(--sp-3);
  margin-bottom: 14px;
}

.room__panel {
  background: var(--panel-solid);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-1);
  padding: 14px;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.room__panel-title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  margin: 0;
}

.room__panel-desc {
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.6;
  margin: 0;
}

.room__share-row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-3);
}

.room__share-count {
  font-size: 13px;
  color: var(--text-2);
}

.room__codebox {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 10px var(--sp-3);
  border: 1px dashed var(--accent);
  border-radius: var(--r-md);
  background: var(--bg-soft-solid);
}

.room__codebox-label {
  font-size: 12px;
  color: var(--text-3);
}

.room__codebox-value {
  font-size: 20px;
  font-weight: 700;
  letter-spacing: 4px;
  color: var(--accent);
}

.room__codebox-expire {
  font-size: 11px;
  color: var(--text-3);
}

.room__rooms {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.room__rooms-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.room__share {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
}

.room__input {
  width: 200px;
  padding: 7px 10px;
  font-size: 13px;
  color: var(--text);
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  outline: none;
  text-transform: uppercase;
  transition: border-color var(--dur-1) var(--ease), box-shadow var(--dur-1) var(--ease);
}

.room__input:focus {
  border-color: var(--accent);
  box-shadow: var(--ring);
}

.room__btn {
  padding: 7px 14px;
  font-size: 13px;
  color: var(--text);
  background: var(--panel);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  cursor: pointer;
  transition: border-color var(--dur-1) var(--ease), color var(--dur-1) var(--ease), background-color var(--dur-1) var(--ease);
}

.room__btn:hover {
  border-color: var(--accent);
  color: var(--accent);
}

.room__btn:active:not(:disabled) {
  background: var(--press-tint);
}

.room__btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.room__btn--primary {
  background: var(--accent);
  border-color: var(--accent);
  color: var(--on-accent);
}

.room__btn--primary:hover {
  background: var(--accent-hover);
  border-color: var(--accent-hover);
  color: var(--on-accent);
}

.room__btn--primary:disabled:hover {
  background: var(--accent);
  border-color: var(--accent);
}

.room__error {
  padding: 10px var(--sp-3);
  font-size: 13px;
  color: var(--danger-text);
  background: var(--danger-bg);
  border: 1px solid color-mix(in srgb, var(--danger-text) 40%, transparent);
  border-left-width: 3px;
  border-radius: var(--r-sm);
  margin-bottom: var(--sp-3);
}

.room__hint {
  padding: 10px var(--sp-3);
  font-size: 13px;
  color: var(--warn-text);
  background: var(--warn-bg);
  border: 1px solid color-mix(in srgb, var(--warn-text) 40%, transparent);
  border-left-width: 3px;
  border-radius: var(--r-sm);
  margin-bottom: var(--sp-3);
}

.room__list {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.room__card {
  background: var(--panel-solid);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-1);
  padding: var(--sp-3) 14px;
}

.room__head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 6px;
}

.room__name {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}

.room__count {
  font-size: 12px;
  color: var(--text-3);
}

.room__meta {
  display: flex;
  flex-wrap: wrap;
  gap: var(--sp-3);
  font-size: 12px;
  color: var(--text-3);
  margin-bottom: 10px;
}

.room__foot {
  display: flex;
  justify-content: space-between;
  align-items: center;
  gap: var(--sp-3);
}

.room__code {
  font-size: 13px;
  color: var(--accent);
  letter-spacing: 1px;
}

.room__code--empty {
  color: var(--text-3);
}

.room__actions {
  display: flex;
  gap: var(--sp-2);
}

.room__empty {
  padding: 40px 0;
  text-align: center;
  font-size: 13px;
  color: var(--text-3);
}
</style>
