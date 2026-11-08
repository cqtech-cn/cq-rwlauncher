<script setup lang="ts">
/**
 * 首次关闭时的"最小化 / 退出"询问弹窗。
 * 由 App.vue 挂载并控制 visible。
 */
import { ref, watch } from 'vue'
import { useI18n } from 'vue-i18n'
import { configApi, windowApi } from '@/api/pywebview'

const { t } = useI18n()

const props = defineProps<{ visible: boolean }>()
const emit = defineEmits<{
  (e: 'update:visible', v: boolean): void
  (e: 'resolved', behavior: 'minimize' | 'exit'): void
}>()

const close = () => emit('update:visible', false)

const onMinimize = async () => {
  await configApi.setCloseBehavior('minimize')
  close()
  emit('resolved', 'minimize')
}

const onExit = async () => {
  await configApi.setCloseBehavior('exit')
  close()
  emit('resolved', 'exit')
}
</script>

<template>
  <el-dialog
    :model-value="props.visible"
    :title="t('firstClose.title')"
    width="380px"
    :show-close="false"
    :close-on-click-modal="false"
    :close-on-press-escape="false"
    align-center
    @update:model-value="(v: boolean) => emit('update:visible', v)"
  >
    <div class="first-close">
      {{ t('firstClose.question') }}
      <ul class="first-close__list">
        <li><b>{{ t('firstClose.minimize') }}</b>：{{ t('firstClose.minimizeDesc') }}</li>
        <li><b>{{ t('firstClose.exit') }}</b>：{{ t('firstClose.exitDesc') }}</li>
      </ul>
      <p class="first-close__note">
        {{ t('firstClose.remember') }}
      </p>
    </div>
    <template #footer>
      <el-button @click="onMinimize">{{ t('firstClose.minimize') }}</el-button>
      <el-button type="primary" @click="onExit">{{ t('firstClose.exit') }}</el-button>
    </template>
  </el-dialog>
</template>

<style scoped>
.first-close {
  padding: var(--sp-2) 0;
  color: var(--text-2);
  line-height: 1.8;
}

.first-close__list {
  margin: var(--sp-2) 0 0 0;
  padding-left: var(--sp-5);
  color: var(--text-3);
  font-size: 12px;
}

.first-close__note {
  margin-top: var(--sp-3);
  font-size: 12px;
  color: var(--text-4);
}
</style>
