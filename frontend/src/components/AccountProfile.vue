<script setup lang="ts">
import { useI18n } from 'vue-i18n'

defineProps<{ username: string }>()
const emit = defineEmits<{ logout: [] }>()

const { t } = useI18n()
</script>

<template>
  <div class="profile">
    <div class="profile__welcome">
      <div class="profile__avatar">{{ username.slice(0, 1).toUpperCase() }}</div>
      <div>
        <div class="profile__username">{{ username }}</div>
        <div class="profile__sub">{{ t('account.currentUserSub') }}</div>
      </div>
    </div>

    <el-button class="profile__logout" @click="emit('logout')">
      {{ t('account.logout') }}
    </el-button>
  </div>
</template>

<style scoped>
.profile__welcome {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: var(--sp-5);
}

.profile__avatar {
  width: 48px;
  height: 48px;
  border-radius: var(--r-full);
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 22px;
  font-weight: 700;
  color: var(--accent);
  background: var(--selected-tint);
  border: 1px solid color-mix(in srgb, var(--accent) 30%, transparent);
}

.profile__username {
  font-size: 18px;
  font-weight: 600;
  color: var(--text);
}

.profile__sub {
  margin-top: var(--sp-1);
  font-size: 13px;
  color: var(--text-3);
}

.profile__logout {
  width: 100%;
}
</style>
