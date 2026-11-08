<script setup lang="ts">
/**
 * 教程页：全屏设置、Steam 版接入、FRP 内网穿透、常见问题。
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()
const fullscreenSteps = computed<{ title: string; desc: string }[]>(() => [
  { title: t('tutorial.fsMethod1'), desc: t('tutorial.fsMethod1Desc') },
  { title: t('tutorial.fsMethod2'), desc: t('tutorial.fsMethod2Desc') },
  { title: t('tutorial.fsMethod3'), desc: t('tutorial.fsMethod3Desc') },
])

const steamSteps = computed<string[]>(() => [
  t('tutorial.steamStep1'),
  t('tutorial.steamStep2'),
  t('tutorial.steamStep3'),
  t('tutorial.steamStep4'),
  t('tutorial.steamStep5'),
])

const frpSteps = computed<{ title: string; desc: string }[]>(() => [
  { title: t('tutorial.frpStep1'), desc: t('tutorial.frpStep1Desc') },
  { title: t('tutorial.frpStep2'), desc: t('tutorial.frpStep2Desc') },
  { title: t('tutorial.frpStep3'), desc: t('tutorial.frpStep3Desc') },
  { title: t('tutorial.frpStep4'), desc: t('tutorial.frpStep4Desc') },
])

const faq = computed<{ q: string; a: string }[]>(() => [
  { q: t('tutorial.faq1Q'), a: t('tutorial.faq1A') },
  { q: t('tutorial.faq2Q'), a: t('tutorial.faq2A') },
  { q: t('tutorial.faq3Q'), a: t('tutorial.faq3A') },
  { q: t('tutorial.faq4Q'), a: t('tutorial.faq4A') },
  { q: t('tutorial.faq5Q'), a: t('tutorial.faq5A') },
])
</script>

<template>
  <div class="tutorial">
    <div class="tutorial__inner">
      <div class="tutorial__header">
        <h1 class="tutorial__title">{{ t('tutorial.title') }}</h1>
        <div class="tutorial__subtitle">{{ t('tutorial.subtitle') }}</div>
      </div>

      <!-- 游戏全屏 -->
      <section class="tutorial__section">
        <h2 class="tutorial__section-title">{{ t('tutorial.fullscreen') }}</h2>
        <div class="tutorial__steps">
          <div v-for="(s, i) in fullscreenSteps" :key="i" class="tutorial__step">
            <span class="tutorial__no">{{ i + 1 }}</span>
            <div class="tutorial__step-body">
              <div class="tutorial__step-title">{{ s.title }}</div>
              <div class="tutorial__step-desc">{{ s.desc }}</div>
            </div>
          </div>
        </div>
      </section>

      <!-- Steam 版接入 -->
      <section class="tutorial__section">
        <h2 class="tutorial__section-title">{{ t('tutorial.steam') }}</h2>
        <div class="tutorial__hint">
          {{ t('tutorial.steamHint') }}
        </div>
        <ol class="tutorial__ol">
          <li v-for="(s, i) in steamSteps" :key="i">{{ s }}</li>
        </ol>
      </section>

      <!-- FRP 内网穿透 -->
      <section class="tutorial__section">
        <h2 class="tutorial__section-title">{{ t('tutorial.frp') }}</h2>
        <div class="tutorial__hint">
          {{ t('tutorial.frpHint') }}
        </div>
        <div class="tutorial__steps">
          <div v-for="(s, i) in frpSteps" :key="i" class="tutorial__step">
            <span class="tutorial__no">{{ i + 1 }}</span>
            <div class="tutorial__step-body">
              <div class="tutorial__step-title">{{ s.title }}</div>
              <div class="tutorial__step-desc">{{ s.desc }}</div>
            </div>
          </div>
        </div>
      </section>

      <!-- 常见问题 -->
      <section class="tutorial__section">
        <h2 class="tutorial__section-title">{{ t('tutorial.faq') }}</h2>
        <div class="tutorial__faq">
          <div v-for="(f, i) in faq" :key="i" class="tutorial__faq-item">
            <div class="tutorial__faq-q">{{ f.q }}</div>
            <div class="tutorial__faq-a">{{ f.a }}</div>
          </div>
        </div>
      </section>
    </div>
  </div>
</template>

<style scoped>
.tutorial {
  height: 100%;
  width: 100%;
  overflow-y: auto;
  background: transparent;
}
.tutorial__inner {
  max-width: 720px;
  width: 100%;
  margin: 0 auto;
  padding: var(--sp-8) var(--sp-6) 40px;
  display: flex;
  flex-direction: column;
  gap: var(--sp-6);
}
.tutorial__header {
  margin-bottom: var(--sp-1);
}
.tutorial__title {
  font-size: 22px;
  font-weight: 700;
  color: var(--text);
  margin: 0 0 var(--sp-1);
}
.tutorial__subtitle {
  font-size: 12px;
  color: var(--text-3);
}
.tutorial__section {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}
.tutorial__section-title {
  position: relative;
  font-size: 14px;
  font-weight: 600;
  color: var(--text);
  padding-bottom: var(--sp-2);
}
.tutorial__section-title::after {
  content: "";
  position: absolute;
  left: 0;
  right: 0;
  bottom: 0;
  height: 1px;
  background: linear-gradient(90deg, var(--border), transparent);
}
.tutorial__hint {
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.7;
  padding: 10px var(--sp-3);
  background: var(--info-bg);
  border-radius: var(--r-sm);
}
.tutorial__steps {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.tutorial__step {
  display: flex;
  align-items: flex-start;
  gap: var(--sp-3);
}
.tutorial__no {
  flex-shrink: 0;
  width: 20px;
  height: 20px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-top: 2px;
  font-size: 11px;
  font-weight: 600;
  color: var(--on-accent);
  background: var(--accent);
  border-radius: var(--r-full);
}
.tutorial__step-body {
  flex: 1;
  min-width: 0;
}
.tutorial__step-title {
  font-size: 13px;
  font-weight: 500;
  color: var(--text);
  margin-bottom: 2px;
}
.tutorial__step-desc {
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.7;
}
.tutorial__ol {
  margin: 0;
  padding-left: var(--sp-5);
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
  font-size: 12px;
  color: var(--text-2);
  line-height: 1.7;
}
.tutorial__faq {
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.tutorial__faq-item {
  border: 1px solid var(--border);
  border-radius: var(--r-md);
  box-shadow: var(--shadow-1);
  background: var(--panel-solid);
  padding: var(--sp-3) 14px;
  display: flex;
  flex-direction: column;
  gap: var(--sp-1);
}
.tutorial__faq-q {
  font-size: 13px;
  font-weight: 600;
  color: var(--text);
}
.tutorial__faq-a {
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.7;
}
</style>
