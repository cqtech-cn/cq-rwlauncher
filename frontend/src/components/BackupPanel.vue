<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { backupApi, configApi, resourceApi, type BackupStatus, type ProfileMod } from '@/api/pywebview'

const { t } = useI18n()

/** 备份状态 */
const backup = ref<BackupStatus>({
  ok: true, logged_in: false, mode: 'none', auto_enabled: true, preferences_path: '',
  preferences_exists: false, backup_mods: 0, installed_mods: 0, installed_maps: 0, last_backup_at: '',
})
const backupBusy = ref(false)
const restoring = ref(false)

/** 恢复弹窗 */
const showRestore = ref(false)
const restoreMods = ref<ProfileMod[]>([])
const restoreInfo = ref('')
const downloadingAll = ref(false)

const loadBackup = async () => {
  try {
    backup.value = await backupApi.status()
  } catch { /* 服务离线 静默 */ }
}

const onBackupNow = async () => {
  backupBusy.value = true
  try {
    const res = await backupApi.backupNow()
    if (res.ok) {
      if (res.mode === 'local') {
        ElMessage.success(t('account.msg.backupLocal', { count: res.mods ?? 0 }))
      } else {
        ElMessage.success(t('account.msg.backupCloud', { count: res.mods ?? 0 }))
      }
    } else {
      ElMessage.error(res.detail || res.error || t('account.msg.backupFailed'))
    }
  } finally {
    backupBusy.value = false
    await loadBackup()
  }
}

const onRestore = async () => {
  restoring.value = true
  try {
    const res = await backupApi.restore()
    if (!res.ok) {
      ElMessage.error(res.detail || res.error || t('account.msg.restoreFailed'))
      return
    }
    const parts: string[] = []
    if (res.mode === 'local') parts.push(t('account.msg.restoredLocal'))
    else parts.push(t('account.msg.restoredCloud'))
    if (res.restored?.preferences) parts.push(t('account.msg.guestRestored'))
    else parts.push(t('account.msg.noGuest'))
    const mods = res.mods || []
    if (mods.length) parts.push(t('account.msg.foundMods', { count: mods.length }))
    restoreInfo.value = parts.join('，')
    restoreMods.value = mods
    showRestore.value = true
  } finally {
    restoring.value = false
  }
}

const onDownloadAll = async () => {
  if (!restoreMods.value.length) return
  downloadingAll.value = true
  try {
    for (const m of restoreMods.value) {
      try {
        await resourceApi.download(m.kind, m.title, m.url)
      } catch { /* 单个失败不中断 */ }
    }
    ElMessage.success(t('account.msg.dlAllDone'))
    showRestore.value = false
  } finally {
    downloadingAll.value = false
  }
}

const onToggleAuto = async (v: string | number | boolean) => {
  try {
    const res = await configApi.update({ account_backup_enabled: !!v })
    if (!res?.ok) ElMessage.error(t('account.msg.saveFailed'))
  } catch {
    ElMessage.error(t('account.msg.saveFailed'))
  }
}

onMounted(loadBackup)
</script>

<template>
  <div class="backup">
    <div class="backup__hint">{{ t('account.backupHint') }}</div>

    <div class="backup__sec">
      <div class="backup__head">
        <span class="backup__title">{{ t('account.autoBackup') }}</span>
        <span :class="['backup__mode', `backup__mode--${backup.mode}`]">
          {{ backup.mode === 'cloud' ? t('account.modeCloud') : backup.mode === 'local' ? t('account.modeLocal') : t('account.notBackedUp') }}
        </span>
      </div>
      <div class="backup__rows">
        <div class="backup__row">
          <span class="backup__label">{{ t('account.guestFile') }}</span>
          <span class="backup__value">
            <span v-if="backup.preferences_exists" class="backup__ok">
              {{ t('account.guestFound') }}
            </span>
            <span v-else class="backup__warn">
              {{ t('account.guestMissing') }}
            </span>
          </span>
        </div>
        <div class="backup__row">
          <span class="backup__label">{{ t('account.cloudContent') }}</span>
          <span class="backup__value">
            {{ t('account.backupContent', { mods: backup.backup_mods, total: backup.installed_mods, maps: backup.installed_maps }) }}
          </span>
        </div>
        <div class="backup__row">
          <span class="backup__label">{{ t('account.lastBackup') }}</span>
          <span class="backup__value">
            {{ backup.last_backup_at || t('account.notBackedUp') }}
          </span>
        </div>
        <div class="backup__row">
          <span class="backup__label">{{ t('account.autoAfterClose') }}</span>
          <el-switch
            :model-value="backup.auto_enabled"
            size="small"
            @change="onToggleAuto"
          />
        </div>
      </div>
      <div class="backup__actions">
        <el-button :loading="backupBusy" @click="onBackupNow">{{ t('account.backupNow') }}</el-button>
        <el-button :loading="restoring" @click="onRestore">{{ t('account.restore') }}</el-button>
      </div>
    </div>

    <!-- 恢复结果弹窗 -->
    <el-dialog v-model="showRestore" :title="t('account.restoreTitle')" width="440px">
      <div class="backup__restore-info">{{ restoreInfo }}</div>
      <div v-if="restoreMods.length" class="backup__restore-list">
        <div v-for="m in restoreMods" :key="`${m.kind}:${m.title}`" class="backup__restore-item">
          <span class="backup__restore-tag">{{ t(m.kind === 'mod' ? 'account.kindMod' : 'account.kindMap') }}</span>
          <span class="backup__restore-name">{{ m.title }}</span>
        </div>
      </div>
      <template #footer>
        <el-button @click="showRestore = false">{{ t('account.close') }}</el-button>
        <el-button
          v-if="restoreMods.length"
          type="primary"
          :loading="downloadingAll"
          @click="onDownloadAll"
        >
          {{ t('account.downloadAll') }}
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.backup__hint {
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-3);
  background: var(--info-bg);
  padding: 10px var(--sp-3);
  border-radius: var(--r-sm);
  margin-bottom: var(--sp-4);
}

.backup__sec {
  padding: var(--sp-4);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-1);
  background: var(--panel-solid);
}

.backup__head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  margin-bottom: var(--sp-3);
}

.backup__title {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
}

.backup__mode {
  font-size: 12px;
  padding: 2px 10px;
  border-radius: var(--r-full);
}

.backup__mode--cloud {
  color: var(--success-text);
  background: var(--success-bg);
}

.backup__mode--local {
  color: var(--warn-text);
  background: var(--warn-bg);
}

.backup__mode--none {
  color: var(--text-3);
  background: var(--info-bg);
}

.backup__rows {
  display: flex;
  flex-direction: column;
  gap: 10px;
}

.backup__row {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
  font-size: 13px;
  color: var(--text-2);
}

.backup__label {
  color: var(--text-3);
  flex-shrink: 0;
}

.backup__value {
  text-align: right;
}

.backup__ok {
  color: var(--success-text);
}

.backup__warn {
  color: var(--warn-text);
}

.backup__actions {
  display: flex;
  gap: 10px;
  margin-top: 14px;
}

.backup__restore-info {
  font-size: 13px;
  line-height: 1.7;
  color: var(--text-2);
}

.backup__restore-list {
  margin-top: 14px;
  max-height: 260px;
  overflow: auto;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.backup__restore-item {
  display: flex;
  align-items: center;
  gap: 10px;
  font-size: 13px;
  padding: var(--sp-2) 10px;
  border-radius: var(--r-sm);
  background: var(--bg-soft-solid);
}

.backup__restore-tag {
  flex-shrink: 0;
  font-size: 11px;
  padding: 2px var(--sp-2);
  border-radius: var(--r-full);
  color: var(--info-text);
  background: var(--info-bg);
}

.backup__restore-name {
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}
</style>
