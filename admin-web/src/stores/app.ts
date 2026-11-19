// ===========================================================================
// 应用级状态 —— 侧边栏折叠、主题、当前点位
// 持久化由 pinia-plugin-persistedstate 统一处理，刷新后恢复用户偏好。
// ===========================================================================

import { defineStore } from 'pinia'
import { ref, computed, watch } from 'vue'

/** 主题模式 */
export type ThemeMode = 'light' | 'dark' | 'system'

export const useAppStore = defineStore(
  'app',
  () => {
    // ---------- 主题 ----------
    const theme = ref<ThemeMode>('system')

    /** 实际生效的主题（system 时解析为 light/dark） */
    const resolvedTheme = computed<'light' | 'dark'>(() => {
      if (theme.value !== 'system') return theme.value
      return window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light'
    })

    const isDark = computed(() => resolvedTheme.value === 'dark')

    function applyTheme(): void {
      const root = document.documentElement
      if (theme.value === 'system') {
        root.removeAttribute('data-theme')
      } else {
        root.setAttribute('data-theme', theme.value)
      }
    }

    function setTheme(mode: ThemeMode): void {
      theme.value = mode
    }

    function toggleTheme(): void {
      setTheme(isDark.value ? 'light' : 'dark')
    }

    // ---------- 侧边栏 ----------
    const sidebarCollapsed = ref(false)

    function toggleSidebar(): void {
      sidebarCollapsed.value = !sidebarCollapsed.value
    }

    function setSidebarCollapsed(collapsed: boolean): void {
      sidebarCollapsed.value = collapsed
    }

    // ---------- 当前点位 ----------
    const currentPointId = ref<number | null>(null)

    function setCurrentPoint(pointId: number | null): void {
      currentPointId.value = pointId
    }

    // 主题变化时立即应用到根节点（不等待持久化写入）
    watch(theme, () => {
      applyTheme()
    })

    // 系统主题变化时，若处于 system 模式则实时切换
    const mediaQuery = window.matchMedia('(prefers-color-scheme: dark)')
    mediaQuery.addEventListener('change', () => {
      if (theme.value === 'system') applyTheme()
    })

    return {
      theme,
      resolvedTheme,
      isDark,
      setTheme,
      toggleTheme,
      sidebarCollapsed,
      toggleSidebar,
      setSidebarCollapsed,
      currentPointId,
      setCurrentPoint,
    }
  },
  {
    persist: {
      key: 'hg.app',
      storage: localStorage,
      pick: ['theme', 'sidebarCollapsed', 'currentPointId'],
    },
  },
)
