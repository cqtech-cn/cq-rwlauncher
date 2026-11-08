<script setup lang="ts">
/**
 * Steam 版接入教程弹窗。
 * 教用户把启动器指向 Steam 正版《铁锈战争》，下载的模组/地图会直接进入 Steam 版目录。
 */
import { computed } from 'vue'
import { useI18n } from 'vue-i18n'

const { t } = useI18n()

const steps = computed<string[]>(() => [
  t('steamTutorial.step1'),
  t('steamTutorial.step2'),
  t('steamTutorial.step3'),
  t('steamTutorial.step4'),
  t('steamTutorial.step5'),
])

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{
  (e: 'update:visible', v: boolean): void
}>()

const close = () => emit('update:visible', false)
</script>

<template>
  <el-dialog
    :model-value="props.visible"
    :title="t('steamTutorial.title')"
    width="500px"
    align-center
    @update:model-value="(v: boolean) => emit('update:visible', v)"
  >
    <div class="steam-tutorial">
      <p class="steam-tutorial__intro">
        {{ t('steamTutorial.intro') }}
      </p>
      <ol class="steam-tutorial__steps">
        <li v-for="(s, i) in steps" :key="i" class="steam-tutorial__step">
          <span class="steam-tutorial__no">{{ i + 1 }}</span>
          <span class="steam-tutorial__text">{{ s }}</span>
        </li>
      </ol>
    </div>
    <template #footer>
      <el-button type="primary" @click="close">{{ t('steamTutorial.gotIt') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.steam-tutorial {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
  padding: var(--sp-1) 0;
}

.steam-tutorial__intro {
  font-size: 12px;
  color: var(--text-3);
  line-height: 1.7;
  padding: 10px var(--sp-3);
  background: var(--info-bg);
  border-radius: var(--r-sm);
}

.steam-tutorial__steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.steam-tutorial__step {
  display: flex;
  align-items: flex-start;
  gap: 10px;
  font-size: 12px;
  color: var(--text-2);
  line-height: 1.7;
}

.steam-tutorial__no {
  flex-shrink: 0;
  width: 18px;
  height: 18px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  margin-top: 2px;
  font-size: 11px;
  color: var(--on-accent);
  background: var(--accent);
  border-radius: var(--r-full);
}

.steam-tutorial__text {
  flex: 1;
  min-width: 0;
}
</style>
