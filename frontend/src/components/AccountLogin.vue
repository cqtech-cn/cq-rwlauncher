<script setup lang="ts">
import { onMounted, ref } from 'vue'
import { ElMessage } from 'element-plus'
import { useI18n } from 'vue-i18n'
import { authApi } from '@/api/pywebview'

const props = defineProps<{ baseUrl: string; reachable: boolean }>()
const emit = defineEmits<{ success: [] }>()

const { t } = useI18n()

/** 登录 / 注册切换 */
const mode = ref<'login' | 'register'>('login')

/** 表单 */
const username = ref('')
const password = ref('')
const password2 = ref('')
const phone = ref('')
const email = ref('')

/** 算术人机验证 */
const captchaId = ref('')
const captchaPrompt = ref('')
const captchaImage = ref('')
const captchaAnswer = ref('')
const busy = ref(false)

const loadCaptcha = async () => {
  try {
    const res = await authApi.getCaptcha()
    if (res.captcha_id) {
      captchaId.value = res.captcha_id
      captchaPrompt.value = res.prompt || ''
      captchaImage.value = res.image || ''
      captchaAnswer.value = ''
    }
  } catch { /* 服务离线，静默 */ }
}

const onLogin = async () => {
  const u = username.value.trim()
  const ph = phone.value.trim()
  const em = email.value.trim()
  const id = u || ph || em
  if (!id) { ElMessage.warning(t('account.msg.noId')); return }
  if (!password.value) { ElMessage.warning(t('account.msg.noPassword')); return }
  if (!captchaId.value || !captchaAnswer.value.trim()) { ElMessage.warning(t('account.msg.noCaptcha')); return }
  busy.value = true
  try {
    const res = await authApi.login(id, password.value, captchaId.value, captchaAnswer.value.trim())
    if (res.ok) {
      ElMessage.success(t('account.msg.welcomeBack', { name: res.username }))
      emit('success')
    } else {
      ElMessage.error(res.detail || res.error || t('account.msg.loginFailed'))
      await loadCaptcha()
    }
  } finally {
    busy.value = false
  }
}

const onRegister = async () => {
  const u = username.value.trim()
  if (u.length < 2 || u.length > 24) { ElMessage.warning(t('account.msg.nameLen')); return }
  if (password.value.length < 8) { ElMessage.warning(t('account.msg.pwdLen')); return }
  if (!/[A-Z]/.test(password.value) || !/\d/.test(password.value)) {
    ElMessage.warning(t('account.msg.pwdComplex'))
    return
  }
  if (password.value !== password2.value) { ElMessage.warning(t('account.msg.pwdMismatch')); return }
  const ph = phone.value.trim()
  const em = email.value.trim()
  if (!ph && !em) { ElMessage.warning(t('account.msg.noContact')); return }
  if (ph && !/^1\d{10}$/.test(ph)) { ElMessage.warning(t('account.msg.badPhone')); return }
  if (em && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(em)) { ElMessage.warning(t('account.msg.badEmail')); return }
  if (!captchaId.value || !captchaAnswer.value.trim()) { ElMessage.warning(t('account.msg.noCaptcha')); return }
  busy.value = true
  try {
    const res = await authApi.register(u, password.value, captchaId.value, captchaAnswer.value.trim(), ph, em)
    if (res.ok) {
      ElMessage.success(t('account.msg.regOk'))
      emit('success')
    } else {
      ElMessage.error(res.detail || res.error || t('account.msg.regFailed'))
      await loadCaptcha()
    }
  } finally {
    busy.value = false
  }
}

onMounted(loadCaptcha)
</script>

<template>
  <div class="login">
    <div class="login__seg">
      <button
        :class="['login__seg-item', { 'login__seg-item--active': mode === 'login' }]"
        @click="mode = 'login'"
      >
        {{ t('account.login') }}
      </button>
      <button
        :class="['login__seg-item', { 'login__seg-item--active': mode === 'register' }]"
        @click="mode = 'register'"
      >
        {{ t('account.register') }}
      </button>
    </div>

    <div class="login__form">
      <el-input
        v-model="username"
        class="login__input"
        :placeholder="t('account.ph.username')"
        maxlength="24"
        :disabled="busy"
        @keyup.enter="mode === 'login' ? onLogin() : onRegister()"
      />
      <el-input
        v-model="phone"
        class="login__input"
        :placeholder="mode === 'register' ? t('account.ph.phoneReg') : t('account.ph.phoneLogin')"
        maxlength="11"
        :disabled="busy"
        @keyup.enter="mode === 'login' ? onLogin() : onRegister()"
      />
      <el-input
        v-model="email"
        class="login__input"
        :placeholder="mode === 'register' ? t('account.ph.emailReg') : t('account.ph.emailLogin')"
        maxlength="128"
        :disabled="busy"
        @keyup.enter="mode === 'login' ? onLogin() : onRegister()"
      />
      <div class="login__contact-tip">
        <template v-if="mode === 'register'">
          {{ t('account.contactTipReg') }}
        </template>
        <template v-else>
          {{ t('account.contactTipLogin') }}
        </template>
      </div>
      <el-input
        v-model="password"
        class="login__input"
        type="password"
        show-password
        :placeholder="t('account.ph.password')"
        maxlength="64"
        :disabled="busy"
        @keyup.enter="mode === 'login' ? onLogin() : onRegister()"
      />
      <el-input
        v-if="mode === 'register'"
        v-model="password2"
        class="login__input"
        type="password"
        show-password
        :placeholder="t('account.ph.password2')"
        maxlength="64"
        :disabled="busy"
        @keyup.enter="onRegister()"
      />
      <div class="login__captcha">
        <div class="login__captcha-box">
          <img
            v-if="captchaImage"
            :src="`data:image/png;base64,${captchaImage}`"
            class="login__captcha-img"
            :alt="t('account.captchaAlt')"
          />
          <span v-else class="login__captcha-prompt">{{ captchaPrompt || t('account.captchaLoading') }}</span>
          <button
            type="button"
            class="login__captcha-refresh"
            :title="t('account.captchaRefresh')"
            :disabled="busy"
            @click="loadCaptcha"
          >
            {{ t('account.captchaRefresh') }}
          </button>
        </div>
        <el-input
          v-model="captchaAnswer"
          class="login__input"
          :placeholder="t('account.ph.captcha')"
          maxlength="8"
          :disabled="busy"
          @keyup.enter="mode === 'login' ? onLogin() : onRegister()"
        />
      </div>
      <el-button
        type="primary"
        class="login__submit"
        :loading="busy"
        @click="mode === 'login' ? onLogin() : onRegister()"
      >
        {{ mode === 'login' ? t('account.login') : t('account.submitRegister') }}
      </el-button>
    </div>

    <div v-if="!props.reachable" class="login__warn">
      {{ t('account.offlineWarn', { url: props.baseUrl }) }}
    </div>
  </div>
</template>

<style scoped>
.login__seg {
  display: flex;
  gap: 6px;
  padding: var(--sp-1);
  border-radius: var(--r-md);
  background: var(--bg-soft-solid);
  margin-bottom: var(--sp-5);
}

.login__seg-item {
  flex: 1;
  padding: var(--sp-2) 0;
  border: none;
  border-radius: var(--r-sm);
  background: transparent;
  font-size: 14px;
  cursor: pointer;
  color: var(--text-3);
  transition: background-color var(--dur-1) var(--ease), color var(--dur-1) var(--ease);
}

.login__seg-item:hover {
  color: var(--text);
}

.login__seg-item--active {
  color: var(--text);
  background: var(--selected-tint);
  font-weight: 600;
}

.login__form {
  display: flex;
  flex-direction: column;
  gap: var(--sp-3);
}

.login__captcha {
  display: flex;
  flex-direction: column;
  gap: var(--sp-2);
}

.login__captcha-box {
  display: flex;
  align-items: center;
  gap: var(--sp-2);
  min-height: 64px;
  padding: 5px var(--sp-2);
  border: 1px solid var(--border);
  border-radius: var(--r-sm);
  background: var(--bg-soft-solid);
}

.login__captcha-img {
  width: 240px;
  max-width: 100%;
  height: 64px;
  object-fit: contain;
  border-radius: var(--r-xs);
}

.login__captcha-prompt {
  flex: 1;
  font-size: 14px;
  letter-spacing: 1px;
  color: var(--warn-text);
}

.login__captcha-refresh {
  border: none;
  background: transparent;
  color: var(--text-3);
  font-size: 12px;
  cursor: pointer;
  padding: 2px var(--sp-1);
  white-space: nowrap;
  transition: color var(--dur-1) var(--ease);
}

.login__captcha-refresh:hover {
  color: var(--text);
}

.login__input {
  width: 100%;
}

.login__contact-tip {
  font-size: 11px;
  line-height: 1.6;
  color: var(--text-3);
  padding: 0 2px;
}

.login__submit {
  margin-top: var(--sp-1);
}

.login__warn {
  margin-top: var(--sp-4);
  padding: 10px var(--sp-3);
  font-size: 12px;
  font-weight: 600;
  line-height: 1.6;
  color: var(--danger-text);
  background: var(--danger-bg);
  border: 1px solid color-mix(in srgb, var(--danger-text) 40%, transparent);
  border-left-width: 3px;
  border-radius: var(--r-sm);
}
</style>
