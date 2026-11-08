<script setup lang="ts">
import { ref, computed } from 'vue'
import { ElMessage } from 'element-plus'
import {
  resourceApi,
  platformApi,
  type PlatformModFeedback,
  type ResourceItem,
} from '@/api/pywebview'
import { useDownloadsStore, fmt } from '@/stores/downloads'
import { useToastStore } from '@/stores/toast'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps<{
  item: ResourceItem
}>()

const dlStore = useDownloadsStore()
const toast = useToastStore()

// 当前卡片自己的 task_id（点击下载后填入）
const taskId = ref<string | null>(null)

const liveState = computed(() => (taskId.value ? dlStore.get(taskId.value) : null))

const hasTotal = computed(() => {
  const s = liveState.value
  return !!s && s.total > 0
})

const progressPct = computed(() => {
  const s = liveState.value
  if (!s || s.total <= 0) return 0
  return Math.min(100, Math.round((s.downloaded / s.total) * 100))
})

const downloadedText = computed(() => {
  const s = liveState.value
  if (!s) return ''
  const dl = fmt.bytes(s.downloaded || 0)
  if (hasTotal.value) {
    return `${dl} / ${fmt.bytes(s.total)}`
  }
  const sp = s.speed && s.speed > 0 ? ` · ${fmt.speed(s.speed)}` : ''
  return `${dl}${sp}`
})

const status = computed(() => liveState.value?.status ?? 'idle')

const isPlatform = computed(() => props.item.mod_id != null)

const onDownload = async () => {
  if (props.item.installed) return
  try {
    let res
    if (isPlatform.value) {
      res = await platformApi.download(props.item.mod_id!, props.item.title, props.item.kind)
    } else {
      res = await resourceApi.download(props.item.kind, props.item.title, props.item.downurl)
    }
    if (!res.ok) {
      if (res.installed) {
        toast.push(t('resourceCard.msg.alreadyExists'), 'info')
      } else {
        ElMessage.error(res.error || t('resourceCard.msg.dlFailed'))
      }
      return
    }
    if (res.task_id) {
      taskId.value = res.task_id
      dlStore.add(res.task_id)
      toast.push(t('resourceCard.msg.started', { title: props.item.title }), 'info')
    }
  } catch (e: any) {
    ElMessage.error(t('resourceCard.msg.dlFailedErr', { err: e?.message || t('common.unknownError') }))
  }
}

const onCancel = async () => {
  if (!taskId.value) return
  try {
    await resourceApi.cancel(taskId.value)
    toast.push(t('resourceCard.msg.canceled'), 'info')
  } catch (e: any) {
    ElMessage.error(t('resourceCard.msg.cancelFailed', { err: e?.message || t('common.unknownError') }))
  }
}

const onOpenBBS = () => {
  if (!props.item.bbsurl) return
  void loadBBS()
}

const bbsOpen = ref(false)
const bbsHtml = ref('')
const bbsLoading = ref(false)
const bbsError = ref('')

const loadBBS = async () => {
  bbsOpen.value = true
  bbsHtml.value = ''
  bbsError.value = ''
  bbsLoading.value = true
  try {
    const res = await resourceApi.getBbsPost(props.item.bbsurl)
    if (res.ok && res.html) {
      bbsHtml.value = res.html
    } else {
      bbsError.value = res.error || t('resourceCard.msg.postLoadFailed')
    }
  } catch (e: any) {
    bbsError.value = t('resourceCard.msg.postLoadFailedErr', { err: e?.message || t('common.unknownError') })
  } finally {
    bbsLoading.value = false
  }
}

/** 拦截原贴内容里的外链点击，避免跳转外部浏览器 */
const onBbsContentClick = (e: MouseEvent) => {
  const link = (e.target as HTMLElement).closest?.('a')
  if (!link) return
  e.preventDefault()
  ElMessage.info(t('resourceCard.msg.externalBlocked'))
}

// —— 平台 Mod 反馈 ——
const fbOpen = ref(false)
const fbItems = ref<PlatformModFeedback[]>([])
const fbContent = ref('')
const fbLoading = ref(false)
const fbSending = ref(false)

const openFeedback = async () => {
  fbOpen.value = true
  fbContent.value = ''
  await loadFeedbacks()
}

const loadFeedbacks = async () => {
  if (!props.item.mod_id) return
  fbLoading.value = true
  try {
    const res = await platformApi.feedbacks(props.item.mod_id)
    if (res.ok && res.data) {
      fbItems.value = res.data.items || []
    } else {
      fbItems.value = []
      ElMessage.warning(res.error || t('resourceCard.msg.fbLoadFailed'))
    }
  } catch (e: any) {
    fbItems.value = []
    ElMessage.error(t('resourceCard.msg.fbLoadFailedErr', { err: e?.message || t('common.unknownError') }))
  } finally {
    fbLoading.value = false
  }
}

const sendFeedback = async () => {
  if (!props.item.mod_id) return
  const content = fbContent.value.trim()
  if (!content) {
    ElMessage.warning(t('resourceCard.msg.noFbContent'))
    return
  }
  fbSending.value = true
  try {
    const res = await platformApi.feedback(props.item.mod_id, content)
    if (res.ok) {
      ElMessage.success(t('resourceCard.msg.fbSubmitted'))
      fbContent.value = ''
      await loadFeedbacks()
    } else {
      ElMessage.error(res.error || res.detail || t('resourceCard.msg.fbSubmitFailed'))
    }
  } catch (e: any) {
    ElMessage.error(t('resourceCard.msg.fbSubmitFailedErr', { err: e?.message || t('common.unknownError') }))
  } finally {
    fbSending.value = false
  }
}

const fmtSize = (n?: number) => {
  if (!n) return ''
  if (n >= 1024 * 1024 * 1024) return (n / 1024 / 1024 / 1024).toFixed(1) + ' GB'
  if (n >= 1024 * 1024) return (n / 1024 / 1024).toFixed(1) + ' MB'
  if (n >= 1024) return (n / 1024).toFixed(0) + ' KB'
  return n + ' B'
}

const fmtTime = (s?: string) => (s ? s.replace('T', ' ').replace('Z', '') : '')
</script>

<template>
  <div class="res-card" :class="{ 'res-card--installed': item.installed }">
    <div class="res-card__thumb">
      <img
        v-if="item.img"
        :src="item.img"
        :alt="item.title"
        loading="lazy"
        referrerpolicy="no-referrer"
        @error="($event.target as HTMLImageElement).style.display='none'"
      />
      <div v-else class="res-card__placeholder">
        <span>{{ item.kind === 'mod' ? 'MOD' : 'MAP' }}</span>
      </div>
    </div>
    <div class="res-card__body">
      <div class="res-card__title" :title="item.title">{{ item.title }}</div>
      <div v-if="item.version" class="res-card__version">{{ item.version }}</div>
      <div class="res-card__meta">
        <el-tag v-if="item.installed" type="success" size="small">{{ t('resourceCard.installed') }}</el-tag>
        <el-tag
          v-else-if="status === 'downloading' || status === 'extracting' || status === 'pending'"
          type="info"
          size="small"
        >{{ t('resourceCard.downloading') }}</el-tag>
        <el-tag v-else-if="status === 'failed'" type="danger" size="small">{{ t('resourceCard.failed') }}</el-tag>
        <el-tag v-else-if="status === 'completed'" type="success" size="small">{{ t('resourceCard.completed') }}</el-tag>
        <el-tag v-else type="info" size="small">{{ t('resourceCard.notDownloaded') }}</el-tag>
        <span v-if="isPlatform" class="res-card__source">{{ t('resourceCard.platform') }}</span>
        <span v-if="isPlatform && item.uploader" class="res-card__source">
          {{ t('resourceCard.uploader', { name: item.uploader }) }}
        </span>
        <span v-if="isPlatform && item.file_size" class="res-card__source">
          {{ fmtSize(item.file_size) }}
        </span>
        <span v-if="isPlatform && item.downloads != null" class="res-card__source">
          {{ t('resourceCard.downloads', { count: item.downloads }) }}
        </span>
        <a v-if="item.bbsurl" class="res-card__bbs" @click.prevent="onOpenBBS">{{ t('resourceCard.viewThread') }}</a>
        <a v-if="isPlatform" class="res-card__bbs" @click="openFeedback">{{ t('resourceCard.feedback') }}</a>
      </div>
      <div v-if="isPlatform && item.description" class="res-card__desc" :title="item.description">
        {{ item.description }}
      </div>
      <div
        v-if="status === 'downloading' || status === 'extracting'"
        class="res-card__progress"
      >
        <el-progress
          :percentage="status === 'extracting' ? 100 : (hasTotal ? progressPct : 0)"
          :indeterminate="status === 'downloading' && !hasTotal"
          :stroke-width="4"
          :show-text="false"
          :status="status === 'extracting' ? 'success' : undefined"
        />
        <div class="res-card__progress-text">
          <span v-if="status === 'extracting'">{{ t('resourceCard.extracting') }}</span>
          <span v-else>{{ downloadedText }}</span>
        </div>
      </div>
    </div>
    <div class="res-card__action">
      <el-button
        v-if="status === 'downloading' || status === 'extracting' || status === 'pending'"
        size="small"
        @click="onCancel"
      >{{ t('resourceCard.cancel') }}</el-button>
      <el-button
        v-else
        size="small"
        type="primary"
        :disabled="item.installed"
        @click="onDownload"
      >{{ item.installed ? t('resourceCard.installed') : t('resourceCard.download') }}</el-button>
    </div>

    <el-dialog
      v-model="fbOpen"
      :title="t('resourceCard.feedbackTitle', { title: item.title })"
      width="480px"
      append-to-body
      class="fb-dialog"
    >
      <div class="fb-list">
        <div v-if="fbLoading" class="fb-empty">{{ t('resourceCard.loading') }}</div>
        <div v-else-if="fbItems.length === 0" class="fb-empty">{{ t('resourceCard.noFeedback') }}</div>
        <div v-for="f in fbItems" :key="f.id" class="fb-item">
          <div class="fb-item__head">
            <span class="fb-item__user">{{ f.username || t('resourceCard.anonymous') }}</span>
            <span class="fb-item__time">{{ fmtTime(f.created_at) }}</span>
          </div>
          <div class="fb-item__content">{{ f.content }}</div>
        </div>
      </div>
      <div class="fb-form">
        <el-input
          v-model="fbContent"
          type="textarea"
          :rows="3"
          maxlength="500"
          show-word-limit
          :placeholder="t('resourceCard.fbPlaceholder')"
        />
        <el-button
          type="primary"
          :loading="fbSending"
          @click="sendFeedback"
        >{{ t('resourceCard.submit') }}</el-button>
      </div>
    </el-dialog>

    <el-dialog
      v-model="bbsOpen"
      :title="t('resourceCard.viewThread') + ' · ' + item.title"
      width="820px"
      append-to-body
      class="bbs-dialog"
    >
      <div v-if="bbsLoading" class="bbs-state">{{ t('resourceCard.loading') }}</div>
      <div v-else-if="bbsError" class="bbs-state bbs-state--err">{{ bbsError }}</div>
      <article v-else class="bbs-content" v-html="bbsHtml" @click="onBbsContentClick"></article>
    </el-dialog>
  </div>
</template>

<style scoped>
.res-card {
  display: flex;
  gap: var(--sp-3);
  padding: var(--sp-3);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  background: var(--panel-solid);
  box-shadow: var(--shadow-1);
  align-items: stretch;
  transition: box-shadow var(--dur-2) var(--ease), transform var(--dur-2) var(--ease),
    border-color var(--dur-2) var(--ease);
}

/* 悬浮轻微浮起，克制使用 */
.res-card:hover {
  box-shadow: var(--shadow-2);
  border-color: color-mix(in srgb, var(--accent) 34%, var(--border));
  transform: translateY(-1px);
}

.res-card:active {
  transform: translateY(0);
  box-shadow: var(--shadow-1);
}

.res-card--installed {
  background: var(--bg-soft-solid);
}

.res-card__thumb {
  width: 96px;
  height: 64px;
  background: var(--border-soft);
  flex-shrink: 0;
  overflow: hidden;
  display: flex;
  align-items: center;
  justify-content: center;
  border: 1px solid var(--border-soft);
  border-radius: var(--r-sm);
}

.res-card__thumb img {
  width: 100%;
  height: 100%;
  object-fit: cover;
  display: block;
  border-radius: inherit;
}

.res-card__placeholder {
  color: var(--text-4);
  font-size: 11px;
  letter-spacing: 1px;
}

.res-card__body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.res-card__title {
  font-size: 13px;
  color: var(--text);
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.res-card__version {
  font-size: 11px;
  color: var(--accent);
  font-family: "Cascadia Code", "Consolas", "Menlo", monospace;
  line-height: 1.4;
}

.res-card__meta {
  display: flex;
  align-items: center;
  gap: 8px;
  font-size: 12px;
}

.res-card__source {
  color: var(--text-4);
  font-size: 11px;
}

.res-card__desc {
  font-size: 11px;
  color: var(--text-3);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

/* 反馈弹窗 */
.fb-list {
  max-height: 240px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 12px;
}
.fb-empty {
  color: var(--text-4);
  font-size: 12px;
  padding: 16px 0;
  text-align: center;
}
.fb-item {
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--bg-soft-solid);
  padding: var(--sp-2) var(--sp-3);
}
.fb-item__head {
  display: flex;
  justify-content: space-between;
  gap: 8px;
  margin-bottom: 4px;
}
.fb-item__user {
  font-size: 12px;
  color: var(--text);
  font-weight: 500;
}
.fb-item__time {
  font-size: 11px;
  color: var(--text-4);
}
.fb-item__content {
  font-size: 12px;
  color: var(--text-2);
  word-break: break-all;
  white-space: pre-wrap;
}
.fb-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
  align-items: flex-end;
}
.fb-form .el-textarea {
  width: 100%;
}

.res-card__bbs {
  color: var(--text-3);
  font-size: 12px;
  cursor: pointer;
}

.res-card__bbs:hover {
  color: var(--text);
  text-decoration: underline;
}

.res-card__progress {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.res-card__progress-text {
  font-size: 11px;
  color: var(--text-3);
  text-align: right;
}

.res-card__action {
  display: flex;
  align-items: center;
  flex-shrink: 0;
}

/* 底部操作按钮：统一圆角并补充按下反馈 */
.res-card__action :deep(.el-button) {
  border-radius: var(--r-sm);
}
.res-card__action :deep(.el-button:active) {
  transform: translateY(1px);
}

.bbs-state {
  padding: 36px 0;
  text-align: center;
  color: var(--text-4);
  font-size: 13px;
}
.bbs-state--err {
  color: var(--danger-text);
}
.bbs-content {
  padding: 4px 8px 18px;
  max-height: 62vh;
  overflow-y: auto;
  background: var(--panel-solid);
  color: var(--text-2);
  font-size: 13px;
  line-height: 1.8;
  word-break: break-word;
}
.bbs-content :deep(h1),
.bbs-content :deep(h2),
.bbs-content :deep(h3),
.bbs-content :deep(h4) {
  margin: 0 0 16px;
  padding-bottom: 10px;
  border-bottom: 1px solid var(--border);
  color: var(--text);
  font-size: 19px;
  font-weight: 600;
  line-height: 1.4;
}
.bbs-content :deep(h2),
.bbs-content :deep(h3),
.bbs-content :deep(h4) {
  margin-top: 22px;
  font-size: 15px;
}
.bbs-content :deep(p) {
  margin: 0 0 12px;
  white-space: pre-wrap;
}
/* 含截图的段落改为画廊式并排 */
.bbs-content :deep(p:has(img)) {
  display: flex;
  flex-wrap: wrap;
  align-items: flex-start;
  gap: 8px;
}
.bbs-content :deep(ul),
.bbs-content :deep(ol) {
  margin: 0 0 14px;
  padding-left: 24px;
}
.bbs-content :deep(li) {
  margin: 4px 0;
}
.bbs-content :deep(blockquote) {
  margin: 12px 0;
  padding: 8px 12px;
  border-left: 3px solid var(--accent);
  background: var(--bg-soft-solid);
  color: var(--text-3);
}
.bbs-content :deep(img) {
  display: block;
  max-width: 100%;
  max-height: 40vh;
  margin: 4px auto;
  object-fit: contain;
  border-radius: var(--r-sm);
  background: var(--bg-soft-solid);
  border: 1px solid var(--border-soft);
}
/* 隐藏装饰性图片：分类图 / 作者头像 / 等级徽章 / 话题标签 */
.bbs-content :deep(img[data-ignore]),
.bbs-content :deep(a:has(> img[data-ignore])),
.bbs-content :deep(span:has(img[data-ignore])) {
  display: none !important;
}
.bbs-content :deep(table) {
  width: 100%;
  margin: 12px 0;
  border-collapse: collapse;
  font-size: 12px;
}
.bbs-content :deep(th),
.bbs-content :deep(td) {
  padding: 7px 9px;
  border: 1px solid var(--border);
  text-align: left;
}
.bbs-content :deep(th) {
  background: var(--bg-soft-solid);
  color: var(--text);
}
.bbs-content :deep(.jinsom-file-download) {
  display: flex;
  align-items: center;
  justify-content: space-between;
  flex-wrap: wrap;
  gap: 12px;
  margin-top: 18px;
  padding: 12px;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--bg-soft-solid);
  line-height: 1.5;
}
.bbs-content :deep(.jinsom-file-download .name) {
  min-width: 0;
  flex: 1 1 220px;
  overflow-wrap: anywhere;
  color: var(--text);
  font-size: 13px;
  font-weight: 500;
}
.bbs-content :deep(hr) {
  margin: 18px 0;
  border: 0;
  border-top: 1px solid var(--border);
}
.bbs-content :deep(pre) {
  overflow-x: auto;
  padding: 10px 12px;
  background: var(--bg-soft-solid);
  border: 1px solid var(--border);
}
.bbs-content :deep(code) {
  font-family: "Cascadia Code", "Consolas", monospace;
}
.bbs-content :deep(pre),
.bbs-content :deep(code) {
  white-space: pre-wrap;
  word-break: break-all;
}
.bbs-content :deep(.jinsom-file-download .pass) {
  margin-top: 3px;
  color: var(--text-4);
  font-size: 12px;
}
.bbs-content :deep(.jinsom-file-download .btn) {
  flex: 0 0 auto;
  min-width: 54px;
  padding: 4px 10px;
  border: 1px solid var(--border);
  border-radius: var(--r-xs);
  color: var(--accent);
  font-size: 12px;
  cursor: default;
  text-align: center;
}
.bbs-content :deep(.jinsom-file-download .btn:hover) {
  border-color: var(--accent);
}
.bbs-content :deep(.jinsom-file-download .pass:empty),
.bbs-content :deep(.jinsom-file-download .btn:empty) {
  display: none;
}
.bbs-content :deep(a) {
  color: var(--accent);
}
.bbs-content :deep(pre),
.bbs-content :deep(code) {
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
