<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { appApi, configApi, whenReady } from '@/api/pywebview'
import { DISCLAIMER_TEXT } from '@/constants/disclaimer'
import stickerUrl from '@/assets/sticker.png'
import qqUrl from '@/assets/qq-group.jpg'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

// 初始值仅为浏览器开发模式的兜底展示，正式数据由后端 get_app_info 提供
const version = ref('1.8.0')
const buildDate = ref('2026-08')
const apiBase = ref('https://www.rtsbox.cn/api/search_bbs.php')

const config = ref<any>(null)

const loadInfo = async () => {
  try {
    const info = await appApi.info()
    if (info?.version) version.value = info.version
    if (info?.build_date) buildDate.value = info.build_date
  } catch {
    // 浏览器开发模式：保持兜底默认值
  }
  try {
    const c = await configApi.get()
    config.value = c
  } catch {
    // 浏览器开发模式
  }
}

onMounted(async () => {
  await whenReady()
  await loadInfo()
})
</script>

<template>
  <div class="about">
    <div class="about__inner">
      <!-- 品牌区：左对齐（图标+标题） + 右侧贴纸 -->
      <div class="about__brand">
        <div class="about__brand-left">
          <div class="about__logo">
            <svg viewBox="0 0 48 48" width="56" height="56" aria-hidden="true">
              <rect x="2" y="2" width="44" height="44" rx="6" fill="none" stroke="currentColor" stroke-width="1.5"/>
              <text x="24" y="30" text-anchor="middle" font-size="14" font-weight="700" fill="currentColor">RW</text>
              <line x1="14" y1="36" x2="34" y2="36" stroke="currentColor" stroke-width="1.2" stroke-linecap="round"/>
            </svg>
          </div>
          <div class="about__brand-text">
            <h1 class="about__title">RW Launcher</h1>
            <div class="about__subtitle">{{ t('about.subtitle') }}</div>
          </div>
        </div>

        <div class="about__brand-right">
          <img
            class="about__sticker"
            :src="stickerUrl"
            alt="sticker"
            draggable="false"
          />
        </div>
      </div>

      <!-- 官方QQ群：醒目宣传，渐变边缘 -->
      <div class="about__qq">
        <div class="about__qq-info">
          <div class="about__qq-title">{{ t('about.qqTitle') }}</div>
          <div class="about__qq-desc" style="white-space: pre-line">{{ t('about.qqDesc') }}</div>
        </div>
        <img
          class="about__qq-img"
          :src="qqUrl"
          :alt="t('about.qqAlt')"
          draggable="false"
        />
      </div>

      <div class="about__grid">
        <div class="about__card">
          <div class="about__card-label">{{ t('about.version') }}</div>
          <div class="about__card-value">v{{ version }}</div>
        </div>
        <div class="about__card">
          <div class="about__card-label">{{ t('about.buildDate') }}</div>
          <div class="about__card-value">{{ buildDate }}</div>
        </div>
        <div class="about__card">
          <div class="about__card-label">{{ t('about.tech') }}</div>
          <div class="about__card-value">Python · Vue 3 · pywebview</div>
        </div>
        <div class="about__card">
          <div class="about__card-label">{{ t('about.license') }}</div>
          <div class="about__card-value">{{ t('about.licenseValue') }}</div>
        </div>
      </div>

      <div class="about__section">
        <h2 class="about__section-title">{{ t('about.features') }}</h2>
        <ul class="about__features">
          <li>
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path d="M3 8.5L6.5 12L13 4.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <div>
              <div class="about__feature-name">{{ t('about.featureDownload') }}</div>
              <div class="about__feature-desc">{{ t('about.featureDownloadDesc') }}</div>
            </div>
          </li>
          <li>
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path d="M3 8.5L6.5 12L13 4.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <div>
              <div class="about__feature-name">{{ t('about.featureMods') }}</div>
              <div class="about__feature-desc">{{ t('about.featureModsDesc') }}</div>
            </div>
          </li>
          <li>
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path d="M3 8.5L6.5 12L13 4.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <div>
              <div class="about__feature-name">{{ t('about.featureArgs') }}</div>
              <div class="about__feature-desc">{{ t('about.featureArgsDesc') }}</div>
            </div>
          </li>
          <li>
            <svg viewBox="0 0 16 16" width="14" height="14" aria-hidden="true">
              <path d="M3 8.5L6.5 12L13 4.5" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"/>
            </svg>
            <div>
              <div class="about__feature-name">{{ t('about.featurePortable') }}</div>
              <div class="about__feature-desc">{{ t('about.featurePortableDesc') }}</div>
            </div>
          </li>
        </ul>
      </div>

      <div class="about__section">
        <h2 class="about__section-title">{{ t('about.contributors') }}</h2>
        <div class="about__thanks">
          <div class="about__thanks-row">
            <span class="about__thanks-label">CQFISH / CQstudio</span>
            <span>{{ t('about.roleCq') }}</span>
          </div>
          <div class="about__thanks-row">
            <span class="about__thanks-label">贡献者 天锝·马斯克</span>
            <span>{{ t('about.roleTd') }}</span>
          </div>
          <div class="about__thanks-row about__thanks-row--muted">
            <span class="about__thanks-label">{{ t('about.recruiting') }}</span>
            <span>{{ t('about.welcome') }}</span>
          </div>
        </div>
      </div>

      <div class="about__section">
        <h2 class="about__section-title">{{ t('about.thanks') }}</h2>
        <div class="about__thanks">
          <div class="about__thanks-row">
            <span class="about__thanks-label">{{ t('about.thanksGame') }}</span>
            <span>{{ t('about.thanksGameDesc') }}</span>
          </div>
          <div class="about__thanks-row">
            <span class="about__thanks-label">{{ t('about.thanksData') }}</span>
            <span>{{ apiBase }}</span>
          </div>
          <div class="about__thanks-row">
            <span class="about__thanks-label">{{ t('about.thanksUi') }}</span>
            <span>Element Plus · Apache 2.0</span>
          </div>
        </div>
      </div>

      <div class="about__section">
        <h2 class="about__section-title">{{ t('about.disclaimer') }}</h2>
        <ul class="about__disclaimer">
          <li v-for="(item, i) in DISCLAIMER_TEXT" :key="i">{{ item }}</li>
        </ul>
      </div>

      <div class="about__copy">{{ t('about.copy') }}</div>
    </div>

  </div>
</template>

<style scoped>
.about {
  height: 100%;
  width: 100%;
  overflow-y: auto;
  background: transparent;
  display: flex;
  flex-direction: column;
}
.about__inner {
  flex: 1;
  max-width: 760px;
  width: 100%;
  margin: 0 auto;
  padding: var(--sp-8) var(--sp-6) var(--sp-6);
}

/* 品牌区：左对齐（图标+标题） + 右侧贴纸 */
.about__brand {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
  margin-bottom: 28px;
  text-align: left;
}
.about__brand-left {
  display: flex;
  align-items: center;
  gap: 14px;
  min-width: 0;
}
.about__brand-text {
  display: flex;
  flex-direction: column;
  min-width: 0;
}
.about__logo {
  color: var(--accent);
  display: inline-flex;
  flex-shrink: 0;
}
.about__title {
  font-size: 24px;
  font-weight: 700;
  color: var(--text);
  margin: 0 0 2px;
  letter-spacing: 0.5px;
  line-height: 1.2;
}
.about__subtitle {
  font-size: 13px;
  color: var(--text-3);
  line-height: 1.4;
}
.about__brand-right {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: flex-end;
}
.about__sticker {
  display: block;
  height: 96px;
  width: auto;
  max-width: 220px;
  object-fit: contain;
  -webkit-user-drag: none;
  user-select: none;
}

.about__grid {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: var(--sp-2);
  margin-bottom: 28px;
}

/* 官方QQ群宣传区 */
.about__qq {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--sp-4);
  margin-bottom: var(--sp-6);
  padding: 18px var(--sp-5);
  border: 1px solid var(--border);
  border-radius: var(--r-lg);
  box-shadow: var(--shadow-1);
  background: linear-gradient(100deg, var(--accent) 0%, var(--accent) 55%, transparent 100%);
}
.about__qq-info {
  color: var(--on-accent);
}
.about__qq-title {
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 6px;
  letter-spacing: 0.5px;
}
.about__qq-desc {
  font-size: 12px;
  opacity: 0.85;
  line-height: 1.7;
}
.about__qq-img {
  width: 88px;
  height: 88px;
  flex-shrink: 0;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: #ffffff;
  padding: var(--sp-1);
  object-fit: cover;
  -webkit-user-drag: none;
  user-select: none;
}
.about__card {
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-1);
  padding: var(--sp-3) 14px;
  background: var(--bg-soft-solid);
}
.about__card-label {
  font-size: 11px;
  color: var(--text-4);
  margin-bottom: var(--sp-1);
  letter-spacing: 0.4px;
}
.about__card-value {
  font-size: 13px;
  color: var(--text);
  font-weight: 500;
}
.about__section {
  margin-bottom: var(--sp-6);
}
.about__section-title {
  position: relative;
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  margin-bottom: 10px;
  padding-bottom: 6px;
  letter-spacing: 0.5px;
}
.about__section-title::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 1px;
  background: linear-gradient(90deg, var(--border), transparent);
}
.about__features {
  list-style: none;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.about__features li {
  display: flex;
  gap: 10px;
  align-items: flex-start;
  font-size: 13px;
  color: var(--text-2);
}
.about__features li > svg {
  color: var(--accent);
  flex-shrink: 0;
  margin-top: 3px;
}
.about__feature-name {
  color: var(--text);
  font-weight: 500;
  margin-bottom: 2px;
}
.about__feature-desc {
  color: var(--text-3);
  font-size: 12px;
  line-height: 1.6;
}
.about__thanks {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.about__thanks-row {
  display: flex;
  gap: var(--sp-3);
  font-size: 12px;
  color: var(--text-2);
  padding: var(--sp-1) 0;
}
.about__thanks-label {
  color: var(--text-4);
  min-width: 80px;
  flex-shrink: 0;
}
.about__thanks-row--muted {
  color: var(--text-3);
  font-style: italic;
}

.about__links {
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.about__disclaimer {
  margin: 0;
  padding-left: 18px;
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
  font-size: 12px;
  line-height: 1.7;
  color: var(--text-3);
}
.about__link {
  display: flex;
  align-items: center;
  gap: 10px;
  padding: 9px 14px;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--panel-solid);
  text-decoration: none;
  transition: background-color var(--dur-1) var(--ease);
}
.about__link:hover {
  background: var(--hover-tint);
  text-decoration: none;
}
.about__link-name {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  flex-shrink: 0;
}
.about__link-url {
  font-size: 12px;
  color: var(--text-4);
  margin-left: auto;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.about__link svg {
  color: var(--text-4);
  flex-shrink: 0;
}
.about__link:hover svg {
  color: var(--text);
}

.about__copy {
  margin-top: 24px;
  text-align: center;
  font-size: 11px;
  color: var(--text-4);
  letter-spacing: 0.4px;
}

/* 底部广告：固定在底栏，hover 轻微变深 */
.about__ad {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: var(--sp-4);
  padding: var(--sp-3) var(--sp-6);
  background: var(--bg-soft-solid);
  border-top: 1px solid var(--border);
  text-decoration: none;
  color: inherit;
  cursor: pointer;
  transition: background-color var(--dur-1) var(--ease);
}
.about__ad:hover {
  background: var(--bg-mid);
  text-decoration: none;
  color: inherit;
}
.about__ad-img {
  flex-shrink: 0;
  width: 88px;
  height: 56px;
  overflow: hidden;
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--panel-solid);
}
.about__ad-img img {
  display: block;
  width: 100%;
  height: 100%;
  object-fit: cover;
  -webkit-user-drag: none;
  user-select: none;
}
.about__ad-body {
  flex: 1;
  min-width: 0;
  display: flex;
  flex-direction: column;
  gap: 2px;
}
.about__ad-tag {
  display: inline-block;
  font-size: 10px;
  font-weight: 600;
  color: var(--text);
  background: var(--info-bg);
  padding: 1px 6px;
  border-radius: var(--r-xs);
  align-self: flex-start;
  letter-spacing: 0.5px;
  line-height: 1.4;
}
.about__ad-title {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.about__ad-desc {
  font-size: 11px;
  color: var(--text-3);
  line-height: 1.4;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.about__ad-action {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  gap: var(--sp-1);
  font-size: 12px;
  font-weight: 500;
  color: var(--text);
  padding: 6px var(--sp-3);
  border: 1px solid var(--accent);
  border-radius: var(--r-sm);
  background: var(--panel-solid);
  transition: background-color var(--dur-1) var(--ease), color var(--dur-1) var(--ease);
}
.about__ad:hover .about__ad-action {
  background: var(--accent);
  color: var(--on-accent);
}
.about__ad-action svg {
  display: block;
}

/* —— 广告免责说明 —— */
.about__ad-notice {
  flex-shrink: 0;
  display: flex;
  align-items: center;
  justify-content: center;
  gap: 4px;
  padding: 8px 24px;
  font-size: 11px;
  color: var(--text-4);
  background: var(--bg-mid);
  border-top: 1px solid var(--border-soft);
  letter-spacing: 0.3px;
  line-height: 1.4;
}
.about__ad-notice-dot {
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  flex-shrink: 0;
}
.about__ad:hover ~ .about__ad-notice {
  /* hover 广告时免责不变，保持独立 */
}
</style>
