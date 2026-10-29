import { createRouter, createWebHistory } from 'vue-router'
import { getUserInfo, getAuthToken, isSessionExpired } from '@/utils/auth'
import { audit } from '@/utils/audit'

const routes = [
  {
    path: '/login',
    name: 'Login',
    component: () => import('@/views/Login.vue'),
    meta: { public: true }
  },
  {
    path: '/change-password',
    name: 'ChangePassword',
    component: () => import('@/views/ChangePassword.vue'),
    meta: { public: true, allowWhenMustChange: true }
  },
  {
    path: '/',
    name: 'Layout',
    component: () => import('@/views/Layout.vue'),
    redirect: '/home',
    children: [
      {
        path: '/home',
        name: 'Home',
        component: () => import('@/views/Home.vue')
      },
      {
        path: '/meetings',
        name: 'MeetingList',
        component: () => import('@/views/MeetingList.vue')
      },
      {
        path: '/meetings/:id',
        name: 'MeetingDetail',
        component: () => import('@/views/MeetingDetail.vue')
      },
      {
        path: '/templates',
        name: 'Templates',
        component: () => import('@/views/Templates.vue'),
        meta: { adminOnly: true }
      },
      {
        path: '/settings',
        name: 'Settings',
        component: () => import('@/views/Settings.vue'),
        meta: { adminOnly: true }
      },
      {
        path: '/audit-logs',
        name: 'AuditLogs',
        component: () => import('@/views/AuditLogs.vue'),
        meta: { adminOnly: true }
      }
    ]
  }
]

const router = createRouter({
  history: createWebHistory(),
  routes
})

router.beforeEach((to, from, next) => {
  const userInfo = getUserInfo()
  const hasToken = !!getAuthToken()

  // 公开页（/login、/change-password）放行
  if (to.meta.public) {
    if (hasToken && to.path === '/login') {
      // 已登录用户访问 /login → 跳转主页
      next('/home')
      return
    }
    next()
    return
  }

  // 受保护页面：未登录跳 /login
  if (!hasToken || !userInfo) {
    next({ path: '/login', query: { redirect: to.fullPath } })
    return
  }

  // admin-only 页面：非管理员跳 /home
  if (to.meta.adminOnly && !userInfo.is_admin) {
    next({ path: '/home' })
    return
  }

  // 强制改密拦截：除改密页外都不让进
  if (userInfo.must_change_password && !to.meta.allowWhenMustChange) {
    next({ path: '/change-password', query: { forced: '1' } })
    return
  }

  // 已过期清掉并跳登录
  if (isSessionExpired()) {
    next({ path: '/login', query: { redirect: to.fullPath } })
    return
  }

  next()
})

// ——— 路由守卫：每次路由切换记录 page.view ———
router.afterEach((to, from) => {
  // 不记登录页（避免刷一堆 page.view 噪音）
  if (to.path === '/login') return

  const userInfo = getUserInfo()
  if (!userInfo) return  // 未登录不记

  // 从路由路径推断 target_type
  // 例：/meetings → "meeting"，/meetings/123 → "meeting_detail"
  const segments = to.path.split('/').filter(Boolean)
  if (!segments.length) return

  const seg0 = segments[0]
  let targetType = seg0
  if (seg0 === 'meetings' && segments.length > 1) {
    targetType = 'meeting_detail'
  }
  // target_id 用完整路由路径（含 query）
  const targetId = to.fullPath

  audit('page.view', targetType, targetId, {
    from: from.fullPath || '',
  })
})

export default router