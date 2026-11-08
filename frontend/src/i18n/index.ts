import { createI18n } from 'vue-i18n'
import zhCN from '@/locales/zh-CN'
import enUS from '@/locales/en-US'

export type Lang = 'zh-CN' | 'en-US'

export const LANG_KEY = 'rw-lang'

/** 读取本地持久化的语言，非法值回退中文 */
export const resolveLang = (): Lang => {
  try {
    const saved = localStorage.getItem(LANG_KEY)
    if (saved === 'zh-CN' || saved === 'en-US') return saved
  } catch {
    // 忽略读取失败
  }
  return 'zh-CN'
}

/** 切换语言并持久化，返回新语言 */
export const setLang = (lang: Lang): Lang => {
  try {
    localStorage.setItem(LANG_KEY, lang)
  } catch {
    // 忽略写入失败
  }
  return lang
}

const i18n = createI18n({
  legacy: false,
  locale: resolveLang(),
  fallbackLocale: 'zh-CN',
  messages: {
    'zh-CN': zhCN,
    'en-US': enUS,
  },
})

export default i18n
