// ===========================================================================
// 路由表与守卫
//
// 守卫职责：
//   1. 未登录访问受保护路由 → 跳转登录页并携带 redirect
//   2. 已登录访问登录页 → 跳回 redirect 或首页
//   3. 按 meta.roles 过滤菜单（侧边栏从路由表自动生成）
//   4. 设置页面标题
// ===========================================================================

import { createRouter, createWebHistory, type RouteRecordRaw } from 'vue-router'
import { useAuthStore } from '@/stores/auth'
import type { UserRole } from '@/api/types'

/** 路由 meta 扩展 */
declare module 'vue-router' {
  interface RouteMeta {
    /** 页面标题（用于 document.title 与面包屑） */
    title?: string
    /** 允许访问的角色；为空表示仅需登录 */
    roles?: UserRole[]
    /** 权限标识；用于按钮级细粒度控制 */
    permission?: string
    /** 是否在侧边栏菜单中隐藏 */
    hidden?: boolean
    /** 图标名称（Element Plus Icons） */
    icon?: string
    /** 是否免登录（登录页、错误页） */
    public?: boolean
  }
}

const routes: RouteRecordRaw[] = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/login/index.vue'),
    meta: { title: '登录', public: true, hidden: true },
  },
  {
    path: '/',
    component: () => import('@/layouts/AppLayout.vue'),
    redirect: '/dashboard',
    children: [
      {
        path: 'dashboard',
        name: 'Dashboard',
        component: () => import('@/views/dashboard/Index.vue'),
        meta: {
          title: '总览',
          icon: 'Odometer',
          roles: ['super_admin', 'admin', 'reviewer', 'observer'],
        },
      },
      {
        path: 'events',
        name: 'Events',
        component: () => import('@/views/events/Index.vue'),
        meta: {
          title: '检测事件',
          icon: 'Picture',
          roles: ['super_admin', 'admin', 'reviewer', 'observer'],
        },
      },
      {
        path: 'monitor',
        name: 'MonitorLive',
        component: () => import('@/views/monitor/Live.vue'),
        meta: {
          title: '实时监控',
          icon: 'Monitor',
          roles: [
            'super_admin',
            'admin',
            'reviewer',
            'observer',
            'league_officer',
            'counselor',
            'security_officer',
            'auditor',
          ],
        },
      },
      {
        path: 'monitor/config',
        name: 'MonitorConfig',
        component: () => import('@/views/monitor/PointConfig.vue'),
        meta: {
          title: '点位标定',
          icon: 'Setting',
          roles: [
            'super_admin',
            'admin',
            'reviewer',
            'observer',
            'league_officer',
            'counselor',
            'security_officer',
            'auditor',
          ],
          hidden: true,
        },
      },
      {
        path: 'reviews',
        name: 'Reviews',
        component: () => import('@/views/decisions/List.vue'),
        meta: {
          title: '审批中心',
          icon: 'Stamp',
          roles: ['super_admin', 'admin', 'reviewer', 'league_officer'],
        },
      },
      {
        path: 'points',
        name: 'Points',
        component: () => import('@/views/scores/Ledger.vue'),
        meta: { title: '积分管理', icon: 'Coin', roles: ['super_admin', 'admin'] },
      },
      {
        path: 'points/rules',
        name: 'ScoreRules',
        component: () => import('@/views/scores/Rules.vue'),
        meta: { title: '积分规则', icon: 'Coin', roles: ['super_admin', 'admin'], hidden: true },
      },
      {
        path: 'policies',
        name: 'Policies',
        component: () => import('@/views/decisions/Policy.vue'),
        meta: {
          title: '策略配置',
          icon: 'Setting',
          roles: ['super_admin', 'admin', 'league_officer', 'counselor', 'security_officer'],
        },
      },
      {
        path: 'appeals',
        name: 'Appeals',
        component: () => import('@/views/appeals/Index.vue'),
        meta: {
          title: '申诉处理',
          icon: 'ChatDotRound',
          roles: ['super_admin', 'league_officer', 'auditor'],
        },
      },
      {
        path: 'identities-pending',
        name: 'IdentitiesPending',
        component: () => import('@/views/identities/Pending.vue'),
        meta: {
          title: '待识别车辆池',
          icon: 'Guide',
          roles: ['super_admin', 'league_officer', 'counselor', 'security_officer', 'auditor'],
        },
      },
      {
        path: 'identities-vehicles',
        name: 'IdentitiesVehicles',
        component: () => import('@/views/identities/Vehicles.vue'),
        meta: {
          title: '车辆档案',
          icon: 'Van',
          roles: ['super_admin', 'league_officer', 'counselor', 'security_officer', 'auditor'],
        },
      },
      {
        path: 'identities-students',
        name: 'IdentitiesStudents',
        component: () => import('@/views/identities/Students.vue'),
        meta: {
          title: '学生档案',
          icon: 'UserFilled',
          roles: ['super_admin', 'league_officer', 'counselor', 'security_officer', 'auditor'],
        },
      },
      {
        path: 'settings',
        name: 'Settings',
        component: () => import('@/views/settings/Index.vue'),
        meta: { title: '系统设置', icon: 'Setting', roles: ['super_admin'] },
      },
      {
        path: 'models',
        name: 'Models',
        component: () => import('@/views/models/Index.vue'),
        meta: {
          title: '模型管理',
          icon: 'Cpu',
          roles: [
            'super_admin',
            'admin',
            'reviewer',
            'observer',
            'league_officer',
            'counselor',
            'security_officer',
            'auditor',
          ],
        },
      },
      {
        path: 'system/audit-logs',
        name: 'AuditLogs',
        component: () => import('@/views/system/AuditLogs.vue'),
        meta: { title: '审计日志', icon: 'Document', roles: ['super_admin', 'admin', 'auditor'] },
      },
      {
        path: 'system/users',
        name: 'SystemUsers',
        component: () => import('@/views/system/Users.vue'),
        meta: { title: '用户与角色', icon: 'User', roles: ['super_admin'] },
      },
    ],
  },
  {
    path: '/403',
    name: 'Forbidden',
    component: () => import('@/views/error/403.vue'),
    meta: { title: '无访问权限', public: true, hidden: true },
  },
  {
    path: '/:pathMatch(.*)*',
    name: 'NotFound',
    component: () => import('@/views/error/404.vue'),
    meta: { title: '页面不存在', public: true, hidden: true },
  },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

/**
 * 根据当前角色过滤可见路由 —— 侧边栏菜单由此生成。
 * 递归处理嵌套路由，过滤掉 meta.roles 不匹配的子路由。
 */
export function filterRoutesByRole(
  allRoutes: RouteRecordRaw[],
  roles: UserRole[] | null,
): RouteRecordRaw[] {
  if (!roles) return []

  return allRoutes.reduce<RouteRecordRaw[]>((acc, route) => {
    const allowed = route.meta?.roles
    const roleAllowed = !allowed || allowed.some((role) => roles.includes(role))

    if (route.children?.length) {
      const children = filterRoutesByRole(route.children, roles)
      // 子路由全被过滤掉且父路由本身无意义时不保留
      if (children.length === 0 && !roleAllowed) return acc
      acc.push({ ...route, children })
      return acc
    }

    if (roleAllowed) acc.push(route)
    return acc
  }, [])
}

/** 路由守卫 */
router.beforeEach(async (to) => {
  const auth = useAuthStore()

  // 应用启动后首次跳转时，恢复本地会话
  if (!auth.isAuthenticated && auth.user === null) {
    await auth.restoreSession()
  }

  const isPublic = to.meta?.public === true

  if (isPublic) {
    // 已登录用户访问登录页 → 回首页
    if (to.name === 'Login' && auth.isAuthenticated) {
      const redirect = to.query.redirect
      return typeof redirect === 'string' ? redirect : '/'
    }
    return true
  }

  if (!auth.isAuthenticated) {
    const redirect = to.fullPath
    return { name: 'Login', query: { redirect } }
  }

  // 角色校验：不匹配跳 403
  const allowedRoles = to.meta?.roles
  if (allowedRoles && auth.role && !allowedRoles.includes(auth.role)) {
    return { name: 'Forbidden' }
  }

  return true
})

router.afterEach((to) => {
  const appTitle = import.meta.env.VITE_APP_TITLE ?? '校园头盔检测提醒助手'
  document.title = to.meta?.title ? `${to.meta.title} · ${appTitle}` : appTitle
})

export default router
