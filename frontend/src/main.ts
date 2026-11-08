import { createApp } from 'vue'
// Element Plus 采用按需导入（unplugin-vue-components + unplugin-auto-import），
// 不再需要全局 import ElementPlus 和完整 CSS。
// 个别程序化调用的 API（ElMessage, ElMessageBox）也需要从 'element-plus' 单独导入。
import 'element-plus/theme-chalk/src/message.scss'
import 'element-plus/theme-chalk/src/message-box.scss'

import './styles/element-overrides.css'
import './styles/global.css'
import App from './App.vue'
import i18n from './i18n'

const app = createApp(App)
app.use(i18n)
app.mount('#app')
