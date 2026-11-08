<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { saveApi, type SaveBackup, type SaveItem } from '@/api/pywebview'

const { t } = useI18n()

const saveItems = ref<SaveItem[]>([])
const saveDirs = ref<string[]>([])
const saveBackups = ref<SaveBackup[]>([])
const selectedSavePaths = ref<string[]>([])
const saveBusy = ref(false)
const deleteBusy = ref(false)

const fmtSize = (b: number) => {
  if (b < 1024) return `${b} B`
  if (b < 1024 * 1024) return `${(b / 1024).toFixed(1)} KB`
  return `${(b / 1024 / 1024).toFixed(1)} MB`
}
const fmtTime = (ts: number) => {
  if (!ts) return '-'
  const d = new Date(ts * 1000)
  const p = (n: number) => String(n).padStart(2, '0')
  return `${d.getFullYear()}-${p(d.getMonth() + 1)}-${p(d.getDate())} ${p(d.getHours())}:${p(d.getMinutes())}`
}

const loadSaves = async () => {
  try {
    const r = await saveApi.list()
    saveItems.value = r.items || []
    saveDirs.value = r.dirs || []
  } catch {
    saveItems.value = []
    saveDirs.value = []
  }
}

const loadSaveBackups = async () => {
  try {
    const r = await saveApi.backups()
    saveBackups.value = r.items || []
  } catch {
    saveBackups.value = []
  }
}

const onBackupSaves = async (all: boolean) => {
  const paths = all ? undefined : selectedSavePaths.value
  if (!all && (!paths || paths.length === 0)) {
    ElMessage.warning(t('settings.saves.needSelectBackup'))
    return
  }
  saveBusy.value = true
  try {
    const res = await saveApi.backup(paths)
    if (res.ok) {
      ElMessage.success(t('settings.saves.backedUp', { count: res.count, time: res.created }))
      await loadSaveBackups()
    } else {
      ElMessage.error(t('settings.saves.backupFailed', { err: res.error || t('common.unknownError') }))
    }
  } catch (e: any) {
    ElMessage.error(t('settings.saves.backupFailed', { err: e?.message || t('common.unknownError') }))
  } finally {
    saveBusy.value = false
  }
}

const onDeleteSaves = async () => {
  if (selectedSavePaths.value.length === 0) {
    ElMessage.warning(t('settings.saves.needSelectDelete'))
    return
  }
  try {
    await ElMessageBox.confirm(
      t('settings.saves.deleteConfirmMsg', { count: selectedSavePaths.value.length }),
      t('settings.saves.deleteConfirmTitle'),
      { type: 'warning', confirmButtonText: t('settings.saves.deleteConfirmOk'), cancelButtonText: t('settings.saves.deleteConfirmCancel') },
    )
  } catch {
    return
  }
  deleteBusy.value = true
  try {
    const res = await saveApi.delete(selectedSavePaths.value)
    if (res.ok) {
      ElMessage.success(t('settings.saves.deleted', { removed: res.removed }))
    } else {
      ElMessage.error(t('settings.saves.deleteFailed', { err: res.error || t('common.unknownError') }))
    }
    selectedSavePaths.value = []
    await loadSaves()
  } catch (e: any) {
    ElMessage.error(t('settings.saves.deleteFailed', { err: e?.message || t('common.unknownError') }))
  } finally {
    deleteBusy.value = false
  }
}

const onRestoreBackup = async (b: SaveBackup) => {
  try {
    await ElMessageBox.confirm(
      t('settings.saves.restoreConfirmMsg', { time: b.created, count: b.count }),
      t('settings.saves.restoreConfirmTitle'),
      { type: 'warning', confirmButtonText: t('settings.saves.restoreConfirmOk'), cancelButtonText: t('settings.saves.deleteConfirmCancel') },
    )
  } catch {
    return
  }
  try {
    const res = await saveApi.restore(b.name)
    if (res.ok) {
      ElMessage.success(t('settings.saves.restored', { restored: res.restored }))
      await loadSaves()
    } else {
      ElMessage.error(t('settings.saves.restoreFailed', { err: res.error || t('common.unknownError') }))
    }
  } catch (e: any) {
    ElMessage.error(t('settings.saves.restoreFailed', { err: e?.message || t('common.unknownError') }))
  }
}

const onDeleteBackup = async (b: SaveBackup) => {
  try {
    await ElMessageBox.confirm(
      t('settings.saves.deleteBackupConfirmMsg', { time: b.created }),
      t('settings.saves.deleteBackupTitle'),
      { type: 'warning', confirmButtonText: t('settings.saves.deleteConfirmOk'), cancelButtonText: t('settings.saves.deleteConfirmCancel') },
    )
  } catch {
    return
  }
  try {
    const res = await saveApi.deleteBackup(b.name)
    if (res.ok) {
      ElMessage.success(t('settings.saves.backupDeleted'))
      await loadSaveBackups()
    } else {
      ElMessage.error(t('settings.saves.deleteFailed', { err: res.error || t('common.unknownError') }))
    }
  } catch (e: any) {
    ElMessage.error(t('settings.saves.deleteFailed', { err: e?.message || t('common.unknownError') }))
  }
}

const onOpenSavesDir = async () => {
  try {
    const res = await saveApi.openDir()
    if (!res.ok) ElMessage.warning(res.error || t('settings.saves.openDirFailed'))
  } catch (e: any) {
    ElMessage.error(t('settings.saves.openDirErr', { err: e?.message || t('common.unknownError') }))
  }
}

const onSaveSelectionChange = (rows: SaveItem[]) => {
  selectedSavePaths.value = rows.map((r) => r.path)
}

onMounted(async () => {
  await loadSaves()
  await loadSaveBackups()
})
</script>

<template>
  <div class="saves">
    <div class="saves__hint">{{ t('settings.saves.hint') }}</div>

    <div class="saves__row">
      <label class="saves__label">{{ t('settings.saves.dir') }}</label>
      <div class="saves__body">
        <div v-if="saveDirs.length === 0" class="saves__empty">{{ t('settings.saves.noDir') }}</div>
        <div v-for="d in saveDirs" :key="d" class="saves__dir text-mono">{{ d }}</div>
        <el-button size="small" @click="onOpenSavesDir">{{ t('settings.saves.openDir') }}</el-button>
      </div>
    </div>

    <div class="saves__row saves__row--top">
      <label class="saves__label">{{ t('settings.saves.list') }}</label>
      <div class="saves__body">
        <div v-if="saveItems.length === 0" class="saves__empty">{{ t('settings.saves.empty') }}</div>
        <el-table
          v-else
          :data="saveItems"
          size="small"
          max-height="260"
          @selection-change="onSaveSelectionChange"
        >
          <el-table-column type="selection" width="36" />
          <el-table-column prop="name" :label="t('settings.saves.name')" min-width="160" show-overflow-tooltip />
          <el-table-column prop="location" :label="t('settings.saves.location')" width="80" />
          <el-table-column :label="t('settings.saves.size')" width="80">
            <template #default="{ row }">{{ fmtSize(row.size) }}</template>
          </el-table-column>
          <el-table-column :label="t('settings.saves.mtime')" width="140">
            <template #default="{ row }">{{ fmtTime(row.mtime) }}</template>
          </el-table-column>
        </el-table>
        <div class="saves__actions">
          <el-button size="small" type="primary" :loading="saveBusy" @click="onBackupSaves(false)">
            {{ t('settings.saves.backupSelected') }}
          </el-button>
          <el-button size="small" :loading="saveBusy" @click="onBackupSaves(true)">
            {{ t('settings.saves.backupAll') }}
          </el-button>
          <el-button size="small" type="danger" :loading="deleteBusy" @click="onDeleteSaves">
            {{ t('settings.saves.deleteSelected') }}
          </el-button>
        </div>
      </div>
    </div>

    <div class="saves__row saves__row--top">
      <label class="saves__label">{{ t('settings.saves.records') }}</label>
      <div class="saves__body">
        <div v-if="saveBackups.length === 0" class="saves__empty">{{ t('settings.saves.noBackups') }}</div>
        <el-table v-else :data="saveBackups" size="small" max-height="220">
          <el-table-column prop="created" :label="t('settings.saves.backupTime')" min-width="140" />
          <el-table-column :label="t('settings.saves.count')" width="80">
            <template #default="{ row }">{{ row.count }}{{ t('settings.saves.countUnit') }}</template>
          </el-table-column>
          <el-table-column :label="t('settings.saves.size')" width="90">
            <template #default="{ row }">{{ fmtSize(row.size) }}</template>
          </el-table-column>
          <el-table-column :label="t('settings.saves.action')" width="150">
            <template #default="{ row }">
              <el-button size="small" link type="primary" @click="onRestoreBackup(row as SaveBackup)">{{ t('settings.saves.restore') }}</el-button>
              <el-button size="small" link type="danger" @click="onDeleteBackup(row as SaveBackup)">{{ t('settings.saves.delete') }}</el-button>
            </template>
          </el-table-column>
        </el-table>
      </div>
    </div>
  </div>
</template>

<style scoped>
.saves__hint {
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-3);
  background: var(--info-bg);
  padding: 10px var(--sp-3);
  border-radius: var(--r-sm);
  margin-bottom: var(--sp-4);
  white-space: pre-line;
}

.saves__row {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: var(--sp-4);
}

.saves__row--top {
  align-items: flex-start;
}

.saves__label {
  width: 96px;
  flex-shrink: 0;
  font-size: 12px;
  color: var(--text-3);
  padding-top: 6px;
}

.saves__body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.saves__dir {
  font-size: 11px;
  color: var(--text-3);
  word-break: break-all;
  line-height: 1.5;
}

.saves__empty {
  font-size: 12px;
  color: var(--text-4);
  padding: var(--sp-1) 0;
}

.saves__actions {
  display: flex;
  gap: var(--sp-2);
  margin-top: var(--sp-1);
}

.saves__body :deep(.el-table) {
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  overflow: hidden;
}

.saves__body :deep(.el-table th.el-table__cell) {
  background: var(--bg-mid);
  color: var(--text-3);
  font-size: 11px;
  font-weight: 600;
}

.saves__body :deep(.el-table td.el-table__cell) {
  font-size: 12px;
}

.saves__body :deep(.el-table tr) {
  background: var(--panel-solid);
}
</style>
