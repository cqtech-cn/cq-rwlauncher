<script setup lang="ts">
/**
 * 模组 / 地图通用浏览器。
 * 父组件传入 kind ('mod' | 'map') 决定调用哪个 API。
 *
 * 设计：
 *  - 列表数据由本组件维护
 *  - 单个 ResourceCard 自管理 task_id 和下载进度
 *  - 本组件只负责搜索 / 翻页 / 在下载完成时刷新对应 item 的 installed 状态
 */
import { onMounted, ref, onUnmounted, computed, reactive } from 'vue'
import { ElMessage } from 'element-plus'
import { resourceApi, platformApi, type ResourceItem, whenReady } from '@/api/pywebview'
import { on, RW_EVENTS } from '@/api/events'
import ResourceCard from './ResourceCard.vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const props = defineProps<{ kind: 'mod' | 'map' }>()

/** 数据源：rtsbox=末忆铁锈盒子 / platform=平台自有 */
const source = ref<'rtsbox' | 'platform'>('rtsbox')

const items = ref<ResourceItem[]>([])
const keyword = ref('')
const page = ref(1)
const pageTarget = ref('1')
const pageSize = 20
const loading = ref(false)
const error = ref<string | null>(null)
const hasMore = ref(true)

/**
 * 渠道降级 / 不可用提示条。
 * 账号服务不可用只会影响「平台」渠道，铁锈盒子直连照常可用，
 * 因此这里用醒目的提示条告知用户，而不是把整页判成错误。
 */
const notice = ref<{ kind: 'warn' | 'error'; text: string; detail?: string; action?: 'switch-rtsbox' | 'retry' } | null>(null)

// —— 高级检索 ——
const advancedOpen = ref(false)
const DEEP_PAGES = 5  // 深度检索聚合页数（每页 20 条）
const filters = reactive({
  includes: '',      // 必含词（空格分隔，全部命中标题）
  excludes: '',      // 排除词（空格分隔，任一命中即隐藏）
  status: 'all',     // all / installed / not_installed
  sort: 'default',   // default / version_desc / version_asc
})

const itemKey = (it: ResourceItem) =>
  it.mod_id != null ? `platform:${it.mod_id}` : `${props.kind}:${it.title}:${it.downurl}`

const searchLabel = computed(() => {
  const base = props.kind === 'mod' ? t('browser.searchMods') : t('browser.searchMaps')
  return `${base}${source.value === 'platform' ? t('browser.platformSuffix') : t('browser.rtsboxSuffix')}`
})
const emptyLabel = computed(() => (props.kind === 'mod' ? t('browser.emptyMods') : t('browser.emptyMaps')))

/** 解析版本号（如 v1.2.3 / 2.0版）为数字数组，解析失败返回 [-1] */
const parseVersion = (v: string | undefined): number[] => {
  if (!v) return [-1]
  const m = v.toLowerCase().match(/v?(\d+(?:\.\d+)*)/)
  if (!m) return [-1]
  return m[1].split('.').map(Number)
}

const compareVersion = (a: string | undefined, b: string | undefined): number => {
  const pa = parseVersion(a)
  const pb = parseVersion(b)
  const len = Math.max(pa.length, pb.length)
  for (let i = 0; i < len; i++) {
    const x = pa[i] ?? 0
    const y = pb[i] ?? 0
    if (x !== y) return x - y
  }
  return 0
}

/** 按版本排序：有版本号的参与排序，无版本号的始终排在末尾 */
const sortByVersion = (list: ResourceItem[], desc: boolean): ResourceItem[] => {
  const withVer = list.filter((it) => it.version)
  const withoutVer = list.filter((it) => !it.version)
  withVer.sort((a, b) => {
    const r = compareVersion(a.version, b.version)
    return desc ? -r : r
  })
  return [...withVer, ...withoutVer]
}

/** 本地应用高级筛选 + 排序后的结果 */
const filteredItems = computed<ResourceItem[]>(() => {
  let list = items.value
  const includes = filters.includes.trim().split(/\s+/).filter(Boolean)
  const excludes = filters.excludes.trim().split(/\s+/).filter(Boolean)
  if (includes.length) {
    list = list.filter((it) => includes.every((w) => it.title.includes(w)))
  }
  if (excludes.length) {
    list = list.filter((it) => !excludes.some((w) => it.title.includes(w)))
  }
  if (filters.status === 'installed') list = list.filter((it) => it.installed)
  if (filters.status === 'not_installed') list = list.filter((it) => !it.installed)
  if (filters.sort === 'version_desc') list = sortByVersion(list, true)
  if (filters.sort === 'version_asc') list = sortByVersion(list, false)
  return list
})

/** 是否有筛选条件生效（用于提示"共 N 条"） */
const filterActive = computed(
  () =>
    filters.includes.trim() !== '' ||
    filters.excludes.trim() !== '' ||
    filters.status !== 'all' ||
    filters.sort !== 'default',
)

// —— 按钮翻页：上一页 / 下一页，翻页替换当前列表 ——
/** 平台源返回 total 时可知总页数；0 = 总页数未知（rtsbox 源） */
const totalPages = ref(0)
const hasPrev = computed(() => page.value > 1)

const load = async (reset = true) => {
  if (reset) {
    page.value = 1
    pageTarget.value = '1'
    hasMore.value = true
    totalPages.value = 0
  }
  loading.value = true
  error.value = null
  notice.value = null
  try {
    let newItems: ResourceItem[] = []
    if (source.value === 'platform') {
      // 平台源：按 kind 过滤（地图页只列平台地图）
      const kindFilter = props.kind
      const res = await platformApi.search(keyword.value.trim(), kindFilter, page.value)
      newItems = (res.items || []).map((it) => ({ ...it, source: 'platform' as const }))
      if (res.error) {
        // 平台渠道依赖账号服务；失败只影响本渠道，提示用户切到铁锈盒子
        error.value = newItems.length > 0 ? null : res.error
        totalPages.value = 0
        notice.value = {
          kind: 'error',
          text: t('browser.platformOffline'),
          detail: res.error,
          action: 'switch-rtsbox',
        }
      } else {
        totalPages.value = (res.total || 0) > 0 ? Math.max(1, Math.ceil((res.total || 0) / pageSize)) : 0
      }
    } else {
      const fn = props.kind === 'mod' ? resourceApi.searchMods : resourceApi.searchMaps
      // 高级检索展开时深度拉取多页，本地过滤才有足够数据
      const pages = advancedOpen.value ? DEEP_PAGES : 1
      const res = await fn(keyword.value.trim(), page.value, pages)
      newItems = (res.items || []).map((it) => ({ ...it, source: 'rtsbox' as const }))
      totalPages.value = 0
      if (res.error) {
        error.value = res.error
      } else if (res.fallback_reason) {
        // 代理不可用但本地直连成功：结果照常可用，只做降级提示
        notice.value = {
          kind: 'warn',
          text: t('browser.fallbackNotice'),
          detail: t('browser.fallbackReason', { reason: res.fallback_reason }),
        }
      }
    }

    items.value = newItems
    hasMore.value = newItems.length >= pageSize
  } catch (e: any) {
    error.value = e?.message || t('browser.msg.loadFailed')
  } finally {
    loading.value = false
  }
}

const switchSource = (s: 'rtsbox' | 'platform') => {
  if (source.value === s) return
  source.value = s
  void load(true)
}

const goPage = (p: number) => {
  if (loading.value || p < 1) return
  if (totalPages.value > 0 && p > totalPages.value) return
  if (p === page.value) return
  page.value = p
  pageTarget.value = String(p)
  hasMore.value = true
  void load(false)
}
const prevPage = () => goPage(page.value - 1)
const nextPage = () => {
  if (!hasMore.value) return
  goPage(page.value + 1)
}
const jumpToPage = () => {
  const target = Number(pageTarget.value)
  if (!Number.isInteger(target) || target < 1) {
    pageTarget.value = String(page.value)
    return
  }
  if (totalPages.value > 0 && target > totalPages.value) {
    pageTarget.value = String(totalPages.value)
    return
  }
  goPage(target)
}

const onSearch = () => load(true)

/** 展开 / 收起高级检索面板：展开时重新深度拉取 */
const toggleAdvanced = () => {
  advancedOpen.value = !advancedOpen.value
  if (advancedOpen.value) void load(true)
}

// 监听安装变化（下载完成后由后端 rw:installed:changed 事件通知）
let unsubInstalled: (() => void) | null = null

const handleInstalledChanged = (d: { kind: string; task_id: string }) => {
  if (d.kind !== props.kind) return
  // 下载完成且已落盘，重新加载当前页刷新 installed 状态
  load(true)
}

onMounted(async () => {
  await whenReady()
  await load(true)
  unsubInstalled = on(RW_EVENTS.INSTALLED_CHANGED, handleInstalledChanged)
})

onUnmounted(() => {
  if (unsubInstalled) unsubInstalled()
})

// —— 上传平台 Mod ——
const upOpen = ref(false)
const upTitle = ref('')
const upKind = ref<'mod' | 'map'>(props.kind)
const upVersion = ref('')
const upDesc = ref('')
const upSaving = ref(false)

const openUpload = () => {
  upTitle.value = ''
  upKind.value = props.kind
  upVersion.value = ''
  upDesc.value = ''
  upOpen.value = true
}

const doUpload = async () => {
  if (!upTitle.value.trim()) {
    ElMessage.warning(t('browser.msg.noTitle'))
    return
  }
  upSaving.value = true
  try {
    const res = await platformApi.upload(
      upTitle.value.trim(),
      upKind.value,
      upVersion.value.trim(),
      upDesc.value.trim(),
    )
    if (res.ok) {
      ElMessage.success(t('browser.msg.uploadOk'))
      upOpen.value = false
      void load(true)
    } else {
      ElMessage.error(res.error || res.detail || t('browser.msg.uploadFailed'))
    }
  } catch (e: any) {
    ElMessage.error(t('browser.msg.uploadFailedErr', { err: e?.message || t('common.unknownError') }))
  } finally {
    upSaving.value = false
  }
}
</script>

<template>
  <div class="browser">
    <!-- 渠道降级 / 不可用提示（醒目样式） -->
    <div v-if="notice" :class="['browser__notice', `browser__notice--${notice.kind}`]">
      <span class="browser__notice-icon" aria-hidden="true">
        <svg viewBox="0 0 16 16" width="15" height="15">
          <path d="M8 1.6 15.2 14H0.8L8 1.6Z" fill="none" stroke="currentColor" stroke-width="1.4" stroke-linejoin="round"/>
          <path d="M8 6.2v3.6" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
          <circle cx="8" cy="12" r="0.85" fill="currentColor"/>
        </svg>
      </span>
      <div class="browser__notice-body">
        <div class="browser__notice-text">{{ notice.text }}</div>
        <div v-if="notice.detail" class="browser__notice-detail">{{ notice.detail }}</div>
      </div>
      <button
        v-if="notice.action === 'switch-rtsbox'"
        class="browser__notice-btn"
        @click="switchSource('rtsbox')"
      >{{ t('browser.switchToRtsbox') }}</button>
      <button
        v-else-if="notice.action === 'retry'"
        class="browser__notice-btn"
        @click="load(true)"
      >{{ t('browser.retryProxy') }}</button>
      <button class="browser__notice-close" :title="t('common.close')" @click="notice = null">
        <svg viewBox="0 0 16 16" width="11" height="11" aria-hidden="true">
          <path d="M3.5 3.5l9 9M12.5 3.5l-9 9" stroke="currentColor" stroke-width="1.6" stroke-linecap="round"/>
        </svg>
      </button>
    </div>

    <div class="browser__toolbar">
      <el-input
        v-model="keyword"
        :placeholder="searchLabel"
        clearable
        class="browser__search"
        @keyup.enter="onSearch"
      >
        <template #prefix>
          <svg class="browser__search-icon" viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
            <circle cx="7" cy="7" r="5" fill="none" stroke="currentColor" stroke-width="1.5"/>
            <line x1="10.5" y1="10.5" x2="14" y2="14" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
          </svg>
        </template>
        <template #append>
          <el-button class="browser__search-btn" @click="onSearch">{{ t('browser.search') }}</el-button>
        </template>
      </el-input>
      <el-button class="browser__refresh" @click="load(true)">
        <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
          <path d="M13 8a5 5 0 1 1-1.5-3.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
          <path d="M13 2v3.5h-3.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
        </svg>
        <span>{{ t('browser.refresh') }}</span>
      </el-button>
      <div class="browser__source">
        <button
          class="browser__source-btn"
          :class="{ 'browser__source-btn--active': source === 'rtsbox' }"
          @click="switchSource('rtsbox')"
        >{{ t('browser.rtsbox') }}</button>
        <button
          class="browser__source-btn"
          :class="{ 'browser__source-btn--active': source === 'platform' }"
          @click="switchSource('platform')"
        >{{ t('browser.platform') }}</button>
      </div>
      <el-button v-if="source === 'platform'" class="browser__upload" @click="openUpload">
        <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
          <path d="M8 11V3M5 5.5 8 2l3 3.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
          <path d="M3 11v2h10v-2" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
        <span>{{ t(props.kind === 'mod' ? 'browser.uploadMod' : 'browser.uploadMap') }}</span>
      </el-button>
    </div>

    <div class="browser__advanced-toggle" @click="toggleAdvanced">
      <svg viewBox="0 0 16 16" width="12" height="12" aria-hidden="true">
        <path d="M2 4h12M4.5 8h7M6.5 12h3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
      </svg>
      <span>{{ t('browser.advanced') }}</span>
      <span class="browser__advanced-state">{{ advancedOpen ? t('browser.collapse') : t('browser.expand') }}</span>
    </div>

    <div v-show="advancedOpen" class="browser__advanced">
      <div class="browser__adv-row">
        <label class="browser__adv-label">{{ t('browser.advIncludes') }}</label>
        <el-input v-model="filters.includes" :placeholder="t('browser.advIncludesPh')" size="small" clearable />
      </div>
      <div class="browser__adv-row">
        <label class="browser__adv-label">{{ t('browser.advExcludes') }}</label>
        <el-input v-model="filters.excludes" :placeholder="t('browser.advExcludesPh')" size="small" clearable />
      </div>
      <div class="browser__adv-row">
        <label class="browser__adv-label">{{ t('browser.dlStatus') }}</label>
        <el-select v-model="filters.status" size="small" class="browser__adv-select">
          <el-option :label="t('browser.statusAll')" value="all" />
          <el-option :label="t('browser.statusInstalled')" value="installed" />
          <el-option :label="t('browser.statusNotInstalled')" value="not_installed" />
        </el-select>
        <label class="browser__adv-label">{{ t('browser.sort') }}</label>
        <el-select v-model="filters.sort" size="small" class="browser__adv-select">
          <el-option :label="t('browser.sortDefault')" value="default" />
          <el-option :label="t('browser.sortVersionDesc')" value="version_desc" />
          <el-option :label="t('browser.sortVersionAsc')" value="version_asc" />
        </el-select>
      </div>
      <div v-if="filterActive" class="browser__adv-count">
        {{ t('browser.filteredCount', { count: filteredItems.length }) }}
      </div>
    </div>

    <div class="browser__scroll">
      <div v-if="loading && items.length === 0" class="browser__list">
        <div v-for="n in 4" :key="n" class="ui-skeleton browser__skeleton"></div>
      </div>
      <div v-else-if="error" class="ui-empty">
        <div class="ui-empty__icon">
          <svg viewBox="0 0 16 16" width="30" height="30" aria-hidden="true">
            <path d="M8 1.6 15.2 14H0.8L8 1.6Z" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
            <path d="M8 6.2v3.6" stroke="currentColor" stroke-width="1.4" stroke-linecap="round"/>
            <circle cx="8" cy="12" r="0.85" fill="currentColor"/>
          </svg>
        </div>
        <div class="ui-empty__title">{{ t('browser.msg.loadFailed') }}</div>
        <div class="ui-empty__desc">{{ error }}</div>
      </div>
      <div v-else-if="items.length === 0" class="ui-empty">
        <div class="ui-empty__icon">
          <svg viewBox="0 0 16 16" width="30" height="30" aria-hidden="true">
            <path d="M2.5 4.5h11v8h-11z" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linejoin="round"/>
            <path d="M2.5 7.5h11M6.5 4.5v3" fill="none" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
          </svg>
        </div>
        <div class="ui-empty__title">{{ emptyLabel }}</div>
      </div>
      <div v-else-if="filteredItems.length === 0" class="ui-empty">
        <div class="ui-empty__icon">
          <svg viewBox="0 0 16 16" width="30" height="30" aria-hidden="true">
            <circle cx="7" cy="7" r="4.5" fill="none" stroke="currentColor" stroke-width="1.2"/>
            <line x1="10.4" y1="10.4" x2="14" y2="14" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
          </svg>
        </div>
        <div class="ui-empty__title">{{ t('browser.noFiltered') }}</div>
      </div>
      <div v-else class="browser__list">
        <ResourceCard
          v-for="item in filteredItems"
          :key="itemKey(item)"
          :item="item"
        />
      </div>
    </div>

    <div v-if="!error && (items.length > 0 || loading)" class="browser__pager">
      <el-button :disabled="!hasPrev || loading" @click="prevPage">{{ t('browser.prevPage') }}</el-button>
      <div class="browser__page-jump">
        <el-input
          v-model="pageTarget"
          class="browser__page-input"
          size="small"
          type="number"
          min="1"
          :placeholder="t('browser.pageJumpPlaceholder')"
          :disabled="loading"
          @keyup.enter="jumpToPage"
          @blur="jumpToPage"
        />
        <el-button size="small" :disabled="loading" @click="jumpToPage">{{ t('browser.pageJump') }}</el-button>
      </div>
      <span class="browser__pager-info">
        {{ t('browser.pageInfo', { page }) }}
        <template v-if="totalPages > 0">{{ t('browser.pageTotal', { total: totalPages }) }}</template>
      </span>
      <el-button :disabled="!hasMore || loading" @click="nextPage">{{ t('browser.nextPage') }}</el-button>
    </div>

    <!-- 上传平台 Mod -->
    <el-dialog
      v-model="upOpen"
      :title="t(props.kind === 'mod' ? 'browser.uploadMod' : 'browser.uploadMap') + t('browser.platformSuffix')"
      width="460px"
      append-to-body
      class="up-dialog"
    >
      <div class="up-form">
        <div class="up-row">
          <label class="up-label">{{ t('browser.upTitle') }}</label>
          <el-input v-model="upTitle" :placeholder="t('browser.upTitlePh')" maxlength="60" clearable />
        </div>
        <div class="up-row">
          <label class="up-label">{{ t('browser.upKind') }}</label>
          <el-radio-group v-model="upKind">
            <el-radio value="mod">{{ t('browser.upKindMod') }}</el-radio>
            <el-radio value="map">{{ t('browser.upKindMap') }}</el-radio>
          </el-radio-group>
        </div>
        <div class="up-row">
          <label class="up-label">{{ t('browser.upVersion') }}</label>
          <el-input v-model="upVersion" :placeholder="t('browser.upVersionPh')" maxlength="30" clearable />
        </div>
        <div class="up-row">
          <label class="up-label">{{ t('browser.upDesc') }}</label>
          <el-input
            v-model="upDesc"
            type="textarea"
            :rows="3"
            :placeholder="t('browser.upDescPh')"
            maxlength="500"
            show-word-limit
          />
        </div>
        <div class="up-hint">
          {{ t('browser.upHint') }}
        </div>
      </div>
      <template #footer>
        <el-button @click="upOpen = false">{{ t('browser.cancel') }}</el-button>
        <el-button type="primary" :loading="upSaving" @click="doUpload">{{ t('browser.upSubmit') }}</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<style scoped>
.browser {
  display: flex;
  flex-direction: column;
  height: 100%;
  gap: 12px;
  padding: 16px 20px;
}

.browser__toolbar {
  display: flex;
  gap: 8px;
  align-items: center;
  flex-shrink: 0;
}

/* 渠道降级 / 不可用提示条：保留醒目语义（左粗边 + 语义底色） */
.browser__notice {
  display: flex;
  align-items: center;
  gap: var(--sp-3);
  flex-shrink: 0;
  padding: 10px 14px;
  border: 1px solid transparent;
  border-left-width: 4px;
  border-radius: var(--r-sm);
}
.browser__notice--warn {
  background: var(--warn-bg);
  border-color: var(--warn-text);
  border-left-color: var(--warn-text);
  color: var(--warn-text);
}
.browser__notice--error {
  background: var(--danger-bg);
  border-color: var(--danger-text);
  border-left-color: var(--danger-text);
  color: var(--danger-text);
}
.browser__notice-icon {
  display: inline-flex;
  flex-shrink: 0;
}
.browser__notice-body {
  flex: 1;
  min-width: 0;
}
.browser__notice-text {
  font-size: 12.5px;
  font-weight: 600;
  line-height: 1.5;
}
.browser__notice-detail {
  margin-top: 2px;
  font-size: 11px;
  opacity: 0.78;
  overflow-wrap: anywhere;
}
.browser__notice-btn {
  flex-shrink: 0;
  padding: 5px 12px;
  font-size: 12px;
  font-weight: 600;
  background: transparent;
  color: inherit;
  border: 1px solid currentColor;
  border-radius: var(--r-sm);
  transition: background-color var(--dur-1) var(--ease), opacity var(--dur-1) var(--ease);
}
.browser__notice-btn:hover {
  background: color-mix(in srgb, currentColor 14%, transparent);
}
.browser__notice-close {
  flex-shrink: 0;
  display: inline-flex;
  padding: 2px;
  background: transparent;
  border: none;
  color: inherit;
  opacity: 0.7;
}
.browser__notice-close:hover {
  opacity: 1;
}

/* —— 搜索框突出 —— */
.browser__search {
  flex: 1;
}
.browser__search :deep(.el-input__wrapper) {
  padding: 4px 11px;
  background: var(--panel-solid);
  box-shadow: 0 0 0 1px var(--border) inset !important;
  border-radius: var(--r-sm);
  transition: box-shadow var(--dur-1) var(--ease);
}
.browser__search :deep(.el-input__wrapper:hover) {
  box-shadow: 0 0 0 1px var(--text-3) inset !important;
}
.browser__search :deep(.el-input.is-focus .el-input__wrapper) {
  box-shadow: 0 0 0 1.5px var(--accent) inset !important;
}
.browser__search :deep(.el-input__inner) {
  font-size: 13px;
  height: 32px;
}
.browser__search :deep(.el-input__inner::placeholder) {
  color: var(--text-4);
}
.browser__search-icon {
  color: var(--text-4);
  margin-right: 4px;
  display: block;
}
.browser__search :deep(.el-input-group__append) {
  background: var(--accent);
  border: none;
  padding: 0;
  border-radius: 0 var(--r-sm) var(--r-sm) 0;
}
.browser__search :deep(.el-input-group__append .el-button) {
  background: var(--accent);
  color: var(--on-accent);
  border: none;
  padding: 0 18px;
  height: 32px;
  font-size: 13px;
  margin: 0;
  border-radius: 0;
}
.browser__search :deep(.el-input-group__append .el-button:hover) {
  background: var(--accent-hover);
}

.browser__refresh {
  display: inline-flex;
  align-items: center;
  gap: 4px;
}

.browser__upload {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  flex-shrink: 0;
}

/* 上传对话框 */
.up-form {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.up-row {
  display: flex;
  align-items: center;
  gap: 8px;
}
.up-label {
  font-size: 12px;
  color: var(--text-3);
  width: 56px;
  flex-shrink: 0;
  text-align: right;
}
.up-hint {
  font-size: 11px;
  color: var(--text-4);
  line-height: 1.6;
  padding: 8px 10px;
  border: 1px dashed var(--border);
  background: var(--bg-soft-solid);
}

/* 数据源切换：分段胶囊 */
.browser__source {
  display: inline-flex;
  gap: 2px;
  padding: 2px;
  border: 1px solid var(--border);
  border-radius: var(--r-full);
  background: var(--bg-soft-solid);
  flex-shrink: 0;
}
.browser__source-btn {
  border: 1px solid transparent;
  background: transparent;
  color: var(--text-3);
  font-size: 12px;
  padding: 6px 14px;
  border-radius: var(--r-full);
  cursor: pointer;
  transition: background-color var(--dur-1) var(--ease), color var(--dur-1) var(--ease),
    border-color var(--dur-1) var(--ease);
}
.browser__source-btn--active {
  background: var(--selected-tint);
  border-color: color-mix(in srgb, var(--accent) 45%, transparent);
  color: var(--text);
  font-weight: 600;
}
.browser__source-btn:not(.browser__source-btn--active):hover {
  background: var(--hover-tint);
  color: var(--text);
}

/* 高级检索切换 */
.browser__advanced-toggle {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  font-size: 12px;
  color: var(--text-3);
  cursor: pointer;
  padding: 5px 10px;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: transparent;
  user-select: none;
  align-self: flex-start;
  transition: color var(--dur-1) var(--ease), border-color var(--dur-1) var(--ease);
}
.browser__advanced-toggle:hover {
  color: var(--accent);
  border-color: var(--accent);
}
.browser__advanced-state {
  color: var(--text-4);
  font-size: 11px;
}

/* 高级检索面板 */
.browser__advanced {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: var(--sp-3);
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  background: var(--bg-soft-solid);
}
.browser__adv-row {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}
.browser__adv-label {
  font-size: 12px;
  color: var(--text-3);
  flex-shrink: 0;
}
.browser__adv-select {
  width: 130px;
}
.browser__adv-count {
  font-size: 11px;
  color: var(--text-4);
}

.browser__scroll {
  flex: 1;
  min-height: 0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}

.browser__list {
  display: grid;
  grid-template-columns: repeat(auto-fill, minmax(420px, 1fr));
  gap: var(--sp-3);
}

/* 加载占位骨架卡：与资源卡大致等高，避免布局跳动 */
.browser__skeleton {
  height: 88px;
}

.browser__pager {
  display: flex;
  justify-content: center;
  align-items: center;
  gap: var(--sp-4);
  flex-shrink: 0;
  padding-top: var(--sp-1);
}

/* 分页控件统一圆角与高度 */
.browser__pager :deep(.el-button) {
  border-radius: var(--r-sm);
}
.browser__pager :deep(.el-input__wrapper) {
  border-radius: var(--r-sm);
}
.browser__pager-info {
  font-size: 12px;
  color: var(--text-3);
  min-width: 72px;
  text-align: center;
}
.browser__page-jump {
  display: inline-flex;
  align-items: center;
  gap: 5px;
}
.browser__page-input {
  width: 64px;
}
.browser__page-input :deep(.el-input__inner) {
  text-align: center;
}
</style>
