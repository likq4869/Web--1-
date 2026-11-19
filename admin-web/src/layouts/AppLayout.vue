// =========================================================================== // 应用主布局 ——
侧边栏 + 顶栏 + 内容区 // 风格：Apple HIG。无渐变、无多层阴影、素色背景、留白建立层级。 //
===========================================================================

<template>
  <div class="hg-layout">
    <!-- ============ 侧边栏 ============ -->
    <aside class="hg-sidebar" :class="{ 'is-collapsed': appStore.sidebarCollapsed }">
      <div class="hg-sidebar__brand">
        <div class="hg-sidebar__logo" aria-hidden="true">
          <svg
            viewBox="0 0 24 24"
            width="20"
            height="20"
            fill="none"
            stroke="currentColor"
            stroke-width="1.8"
          >
            <path
              d="M12 3a5 5 0 0 0-5 5v3a5 5 0 0 0 10 0V8a5 5 0 0 0-5-5Z"
              stroke-linejoin="round"
            />
            <path d="M4 12h16" stroke-linecap="round" />
            <path d="M12 3v3" stroke-linecap="round" />
          </svg>
        </div>
        <span v-show="!appStore.sidebarCollapsed" class="hg-sidebar__title">头盔检测助手</span>
      </div>

      <nav class="hg-sidebar__nav" aria-label="主导航">
        <RouterLink
          v-for="item in visibleMenu"
          :key="item.path"
          :to="item.path"
          class="hg-sidebar__item"
          active-class="is-active"
        >
          <ElIcon class="hg-sidebar__icon"><component :is="item.icon" /></ElIcon>
          <span v-show="!appStore.sidebarCollapsed" class="hg-sidebar__label">{{
            item.title
          }}</span>
        </RouterLink>
      </nav>

      <button
        class="hg-sidebar__toggle"
        type="button"
        :aria-label="appStore.sidebarCollapsed ? '展开侧边栏' : '收起侧边栏'"
        @click="appStore.toggleSidebar()"
      >
        <ElIcon><Fold v-if="!appStore.sidebarCollapsed" /><Expand v-else /></ElIcon>
        <span v-show="!appStore.sidebarCollapsed">收起</span>
      </button>
    </aside>

    <!-- ============ 主区域 ============ -->
    <div class="hg-main">
      <!-- 顶栏 -->
      <header class="hg-topbar">
        <!-- 面包屑 -->
        <nav class="hg-topbar__breadcrumb" aria-label="面包屑">
          <span class="hg-topbar__crumb">管理后台</span>
          <template v-if="breadcrumb.length">
            <ElIcon class="hg-topbar__crumb-sep"><ArrowRight /></ElIcon>
            <span class="hg-topbar__crumb hg-topbar__crumb--current">{{
              breadcrumb.join(' / ')
            }}</span>
          </template>
        </nav>

        <div class="hg-topbar__actions">
          <!-- 点位切换器 -->
          <ElSelect
            v-model="pointId"
            class="hg-topbar__point"
            placeholder="全部点位"
            :disabled="pointOptions.length === 0"
            size="default"
          >
            <ElOption label="全部点位" :value="null" />
            <ElOption
              v-for="point in pointOptions"
              :key="point.id"
              :label="point.name"
              :value="point.id"
            />
          </ElSelect>

          <!-- 主题切换 -->
          <button
            class="hg-icon-btn"
            type="button"
            :aria-label="appStore.isDark ? '切换到浅色模式' : '切换到深色模式'"
            @click="appStore.toggleTheme()"
          >
            <ElIcon><Sunny v-if="appStore.isDark" /><Moon v-else /></ElIcon>
          </button>

          <!-- 通知铃铛 -->
          <button class="hg-icon-btn" type="button" aria-label="通知">
            <ElIcon><Bell /></ElIcon>
            <span v-if="pendingCount > 0" class="hg-icon-btn__badge">{{ pendingCount }}</span>
          </button>

          <!-- 用户菜单 -->
          <ElDropdown trigger="click" @command="onUserCommand">
            <button class="hg-user" type="button">
              <span class="hg-user__avatar">{{ initial }}</span>
              <span class="hg-user__name">{{ authStore.user?.display_name ?? '未登录' }}</span>
            </button>
            <template #dropdown>
              <ElDropdownMenu>
                <ElDropdownItem disabled>{{ roleLabel }}</ElDropdownItem>
                <ElDropdownItem divided command="logout">退出登录</ElDropdownItem>
              </ElDropdownMenu>
            </template>
          </ElDropdown>
        </div>
      </header>

      <!-- 内容区 -->
      <main class="hg-content">
        <RouterView v-slot="{ Component }">
          <Transition name="fade" mode="out-in">
            <component :is="Component" />
          </Transition>
        </RouterView>
      </main>
    </div>
  </div>
</template>

<script setup lang="ts">
import { computed, ref } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElIcon } from 'element-plus'
import type { Component as VueComponent } from 'vue'
import {
  ArrowRight,
  Bell,
  Coin,
  Cpu,
  Document,
  Expand,
  Fold,
  Guide,
  Monitor,
  Moon,
  Odometer,
  Picture,
  Setting,
  Stamp,
  Sunny,
  User,
  UserFilled,
  Van,
} from '@element-plus/icons-vue'
import { useAppStore } from '@/stores/app'
import { useAuthStore } from '@/stores/auth'
import { filterRoutesByRole } from '@/router'
import type { MonitoringPoint, UserRole } from '@/api/types'

const route = useRoute()
const router = useRouter()
const appStore = useAppStore()
const authStore = useAuthStore()

// ---------- 侧边栏菜单：从路由表按角色自动生成 ----------
const allRoutes = router.getRoutes()
const visibleMenu = computed(() => {
  const layoutRoute = allRoutes.find((r) => r.path === '/')
  if (!layoutRoute?.children) return []

  const children = filterRoutesByRole(
    layoutRoute.children,
    authStore.role ? [authStore.role] : null,
  )

  return children
    .filter((child) => child.meta?.hidden !== true && child.meta?.title)
    .map((child) => ({
      path: child.path.startsWith('/') ? child.path : `/${child.path}`,
      title: child.meta?.title ?? '',
      icon: resolveIcon(child.meta?.icon),
    }))
})

/** 图标名 → 组件 */
function resolveIcon(name?: string): VueComponent {
  const map: Record<string, VueComponent> = {
    Odometer,
    Picture,
    Stamp,
    Coin,
    Setting,
    Guide,
    Monitor,
    Van,
    UserFilled,
    Cpu,
    Document,
    User,
  }
  return (name && map[name]) || Odometer
}

// ---------- 面包屑 ----------
const breadcrumb = computed(() => {
  const matched = route.matched.filter((r) => r.meta?.title && r.name !== 'root')
  return matched.map((r) => r.meta?.title as string)
})

// ---------- 点位切换 ----------
const pointOptions = ref<MonitoringPoint[]>([])
const pointId = computed({
  get: () => appStore.currentPointId,
  set: (value: number | null) => appStore.setCurrentPoint(value),
})

// ---------- 通知 ----------
const pendingCount = ref(0)

// ---------- 用户 ----------
const initial = computed(() => (authStore.user?.display_name ?? '?').charAt(0))

const roleLabel = computed(() => {
  const labels: Record<UserRole, string> = {
    super_admin: '超级管理员',
    admin: '管理员',
    reviewer: '审核员',
    observer: '观察员',
    league_officer: '团委干事',
    counselor: '辅导员',
    security_officer: '保卫干事',
    auditor: '审计员',
    student: '学生',
  }
  const current = authStore.role
  return current ? labels[current] : '未知角色'
})

async function onUserCommand(command: string): Promise<void> {
  if (command === 'logout') {
    await authStore.logout()
    await router.replace({ name: 'Login' })
  }
}
</script>

<style scoped lang="scss" src="./_styles/app-layout.scss"></style>
