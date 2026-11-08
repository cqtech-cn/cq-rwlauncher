<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const emit = defineEmits<{
  done: []
}>()

// 使用本地 active 控制显示/消失，自包含定时器
const active = ref(true)

onMounted(() => {
  // 动画总时长 ~2s：
  //   入场动画 0.65s + 保持 1s + 过渡退出 0.35s
  setTimeout(() => {
    active.value = false
  }, 2000)
})
</script>

<template>
  <Transition name="splash-fade" appear @after-leave="emit('done')">
    <div v-if="active" class="splash">
      <div class="splash__inner">
        <!-- 图标：缩放 + 淡入 -->
        <div class="splash__icon-wrap">
          <svg class="splash__rocket" viewBox="0 0 48 48" width="48" height="48" aria-hidden="true" role="img">
            <title>CQRWL</title>
            <!-- 火箭主体 -->
            <path d="M24 4C18 12 16 20 16 28h16c0-8-2-16-8-24z"
                  fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
            <!-- 整流罩 -->
            <path d="M24 4a8 8 0 0 1 8 8"
                  fill="none" stroke="currentColor" stroke-width="1.8" stroke-linejoin="round"/>
            <!-- 舷窗 -->
            <circle cx="24" cy="16" r="2.5" fill="none" stroke="currentColor" stroke-width="1.5"/>
            <!-- 尾翼 -->
            <path d="M16 26l-2 6h4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
            <path d="M32 26l2 6h-4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"/>
            <!-- 火焰 -->
            <path d="M20 34c-2 4-1 8-1 8s3-3 5-3 5 3 5 3 1-4-1-8"
                  fill="none" stroke="currentColor" stroke-width="1.5" stroke-linejoin="round"
                  class="splash__flame"/>
            <!-- 轨道弧 -->
            <path d="M10 42c8-6 20-6 28 0"
                  fill="none" stroke="currentColor" stroke-width="1" stroke-dasharray="2 3"
                  opacity="0.3" class="splash__orbit"/>
          </svg>
        </div>

        <!-- 主标题 -->
        <h1 class="splash__title">CQ RWLauncher</h1>

        <!-- 装饰线 -->
        <div class="splash__line" />

        <!-- 副标题 -->
        <p class="splash__subtitle">{{ t('splash.subtitle') }}</p>

        <!-- 缩写 -->
        <span class="splash__abbr">CQRWL</span>
      </div>
    </div>
  </Transition>
</template>

<style scoped>
.splash {
  position: fixed;
  inset: 0;
  z-index: 9999;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  background: var(--bg);
}

.splash__inner {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 14px;
}

/* —— 火箭图标 —— */
.splash__icon-wrap {
  animation: splash-scale-in 0.5s ease-out both;
}

.splash__rocket {
  display: block;
  color: var(--accent);
}

/* 火焰：闪烁动效 */
.splash__flame {
  animation: splash-flicker 0.6s ease-in-out infinite alternate;
}

/* 轨道：旋转动效 */
.splash__orbit {
  animation: splash-spin 3s linear infinite;
  transform-origin: 24px 42px;
}

/* —— 标题 —— */
.splash__title {
  font-size: 22px;
  font-weight: 600;
  color: var(--text);
  letter-spacing: 1.2px;
  margin: 0;
  animation: splash-fade-slide 0.5s ease-out 0.25s both;
}

/* —— 装饰线 —— */
.splash__line {
  width: 40px;
  height: 1px;
  background: var(--accent);
  animation: splash-line-grow 0.35s ease-out 0.5s both;
}

/* —— 副标题 —— */
.splash__subtitle {
  font-size: 13px;
  color: var(--text-3);
  margin: 0;
  animation: splash-fade-slide 0.5s ease-out 0.65s both;
}

/* —— 缩写 —— */
.splash__abbr {
  font-size: 10px;
  letter-spacing: 2.5px;
  color: var(--text-4);
  margin-top: 2px;
  animation: splash-fade-slide 0.5s ease-out 0.85s both;
}

/* Keyframes */

@keyframes splash-scale-in {
  0% {
    opacity: 0;
    transform: scale(0.6);
  }
  100% {
    opacity: 1;
    transform: scale(1);
  }
}

@keyframes splash-fade-slide {
  0% {
    opacity: 0;
    transform: translateY(8px);
  }
  100% {
    opacity: 1;
    transform: translateY(0);
  }
}

@keyframes splash-line-grow {
  0% {
    transform: scaleX(0);
  }
  100% {
    transform: scaleX(1);
  }
}

@keyframes splash-flicker {
  0% {
    opacity: 0.4;
  }
  100% {
    opacity: 1;
  }
}

@keyframes splash-spin {
  0% {
    transform: rotate(0deg);
  }
  100% {
    transform: rotate(360deg);
  }
}

/* —— 退出动画（Transition 的 leave 阶段） —— */
.splash-fade-leave-active {
  transition: opacity 0.35s ease-out;
}
.splash-fade-leave-to {
  opacity: 0;
}
</style>
