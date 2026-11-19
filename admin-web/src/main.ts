// ===========================================================================
// 应用入口
// ===========================================================================

import { createApp } from 'vue'
import { createPinia } from 'pinia'
import piniaPluginPersistedstate from 'pinia-plugin-persistedstate'
import ElementPlus from 'element-plus'
import zhCn from 'element-plus/es/locale/lang/zh-cn'

import App from './App.vue'
import router from './router'

// 样式：Element Plus 主题（Apple 覆写） → 设计令牌 → 基础样式
import './styles/element-theme.scss'
import './styles/reset.scss'
import './styles/typography.scss'
import './styles/utilities.scss'

const app = createApp(App)

const pinia = createPinia()
// 持久化插件：主题、筛选条件等用户偏好写入 localStorage，
// 刷新页面不丢失；各 store 通过 persist 配置显式声明持久化范围。
pinia.use(piniaPluginPersistedstate)

app.use(pinia)
app.use(router)
app.use(ElementPlus, { locale: zhCn })

// 挂载前应用主题，避免首屏闪烁。
// 持久化插件已在 app.use(pinia) 阶段恢复 store 状态，
// 因此此处读到的 theme 已是用户上次选择。
import { useAppStore } from './stores/app'
const appStore = useAppStore()
if (appStore.theme !== 'system') {
  document.documentElement.setAttribute('data-theme', appStore.theme)
}

app.mount('#app')
