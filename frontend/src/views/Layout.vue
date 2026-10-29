<template>
  <el-container class="layout-container">
    <!-- 侧边栏 -->
    <el-aside width="240px" class="sidebar">
      <div class="sidebar-header">
        <div class="logo">
          <AudioLines :size="28" class="logo-icon" />
          <span class="logo-text">智能会议助手</span>
        </div>
      </div>

      <el-menu
        :default-active="activeMenu"
        router
        class="sidebar-menu"
        background-color="transparent"
        text-color="#9c948a"
        active-text-color="#faf8f4"
        :unique-opened="true"
      >
        <el-menu-item index="/home">
          <el-icon><LayoutDashboard /></el-icon>
          <template #title>数据概览</template>
        </el-menu-item>
        <el-menu-item index="/meetings">
          <el-icon><FileText /></el-icon>
          <template #title>会议管理</template>
        </el-menu-item>
        <el-menu-item v-if="userInfo?.is_admin" index="/templates">
          <el-icon><Files /></el-icon>
          <template #title>模板管理</template>
        </el-menu-item>
        <el-menu-item v-if="userInfo?.is_admin" index="/settings">
          <el-icon><Settings /></el-icon>
          <template #title>系统设置</template>
        </el-menu-item>
        <el-menu-item v-if="userInfo?.is_admin" index="/audit-logs">
          <el-icon><ScrollText /></el-icon>
          <template #title>审计日志</template>
        </el-menu-item>
      </el-menu>
    </el-aside>

    <!-- 主内容区 -->
    <el-container class="main-container">
      <el-header class="header">
        <div class="header-left">
          <h3 class="page-title">{{ pageTitle }}</h3>
        </div>
        <div class="header-right">
          <span class="current-time">{{ currentTime }}</span>
          <el-dropdown @command="handleUserCommand">
            <span class="user-info">
              <el-icon><UserCircle /></el-icon>
              {{ userInfo?.姓名 || userInfo?.loginid || '未登录' }}
            </span>
            <template #dropdown>
              <el-dropdown-menu>
                <el-dropdown-item command="changePwd">
                  <el-icon><KeyRound /></el-icon>
                  修改密码
                </el-dropdown-item>
                <el-dropdown-item command="logout" divided>
                  <el-icon><LogOut /></el-icon>
                  退出登录
                </el-dropdown-item>
              </el-dropdown-menu>
            </template>
          </el-dropdown>
        </div>
      </el-header>

      <el-main class="main-content">
        <router-view />
      </el-main>
    </el-container>
  </el-container>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { AudioLines, LayoutDashboard, FileText, Files, Settings, UserCircle, LogOut, KeyRound, ScrollText } from 'lucide-vue-next'
import { ElMessage, ElMessageBox } from 'element-plus'
import { now } from '@/utils/timezone'
import { getUserInfo, logout as clearAuth } from '@/utils/auth'
import api from '@/api'

const route = useRoute()
const router = useRouter()
const currentTime = ref('')

const userInfo = ref(getUserInfo())

const activeMenu = computed(() => {
  if (route.path.startsWith('/meetings/')) return '/meetings'
  return route.path
})

const pageTitles = {
  '/home': '数据概览',
  '/meetings': '会议管理',
  '/templates': '模板管理',
  '/settings': '系统设置',
  '/audit-logs': '审计日志'
}

const pageTitle = computed(() => {
  if (route.path.startsWith('/meetings/')) return '会议详情'
  return pageTitles[route.path] || '智能会议助手'
})

function updateTime() {
  currentTime.value = now().format('YYYY-MM-DD HH:mm:ss')
}

async function handleUserCommand(cmd) {
  if (cmd === 'logout') {
    try {
      await ElMessageBox.confirm('确定退出登录？', '提示', {
        type: 'warning',
        confirmButtonText: '退出',
        cancelButtonText: '取消'
      })
    } catch { return }
    try {
      await api.auth.logout()
    } catch { /* 即便后端失败，前端也清掉 */ }
    clearAuth()
    ElMessage.success('已退出')
    router.push('/login')
  } else if (cmd === 'changePwd') {
    ElMessageBox.prompt('请输入新密码（至少 6 位）', '修改密码', {
      confirmButtonText: '修改',
      cancelButtonText: '取消',
      inputType: 'password',
      inputValidator: (val) => (val && val.length >= 6) || '密码至少 6 位'
    })
      .then(async ({ value }) => {
        try {
          // 旧密码校验：让用户输入旧密码后再确认
          const { value: oldPwd } = await ElMessageBox.prompt('请输入当前密码', '身份验证', {
            inputType: 'password',
            confirmButtonText: '下一步',
          })
          await api.auth.changePassword({ old_password: oldPwd, new_password: value })
          ElMessage.success('密码已修改')
        } catch (e) {
          if (e !== 'cancel' && e !== 'close') {
            ElMessage.error(e?.response?.data?.detail || '修改失败')
          }
        }
      })
      .catch(() => {})
  }
}

let timeInterval = null

onMounted(() => {
  updateTime()
  timeInterval = setInterval(updateTime, 1000)
})

onUnmounted(() => {
  if (timeInterval) {
    clearInterval(timeInterval)
  }
})
</script>

<style scoped>
.layout-container {
  height: 100vh;
  background: var(--mc-paper);
}

/* 侧边栏：墨色 */
.sidebar {
  background: var(--mc-ink);
  display: flex;
  flex-direction: column;
}

.sidebar-header {
  padding: 24px 20px 20px;
  border-bottom: 1px solid rgba(250, 248, 244, 0.08);
}

.logo {
  display: flex;
  align-items: center;
  gap: 12px;
}

.logo-icon {
  color: var(--mc-accent);
  flex-shrink: 0;
}

.logo-text {
  font-family: var(--mc-font-display);
  font-size: 19px;
  font-weight: 700;
  color: #faf8f4;
  letter-spacing: 0.04em;
}

.sidebar-menu {
  flex: 1;
  border-right: none;
  background: transparent;
  padding: 12px 0;
}

:deep(.el-menu-item) {
  height: 44px;
  line-height: 44px;
  margin: 2px 12px;
  border-radius: var(--mc-radius-sm);
  font-size: 13.5px;
  transition: background var(--mc-duration) var(--mc-ease), color var(--mc-duration) var(--mc-ease);
}

:deep(.el-menu-item:hover) {
  background: rgba(250, 248, 244, 0.06) !important;
  color: #faf8f4 !important;
}

:deep(.el-menu-item.is-active) {
  background: color-mix(in srgb, var(--mc-accent) 16%, transparent) !important;
  color: #faf8f4 !important;
}

:deep(.el-menu-item.is-active .el-icon) {
  color: var(--mc-accent);
}

:deep(.el-menu-item.is-active::before) {
  content: '';
  position: absolute;
  left: 0;
  top: 50%;
  transform: translateY(-50%);
  width: 3px;
  height: 20px;
  background: var(--mc-accent);
  border-radius: 0 2px 2px 0;
}

/* 主内容区 */
.main-container {
  display: flex;
  flex-direction: column;
}

.header {
  background: var(--mc-paper);
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 0 28px;
  border-bottom: 1px solid var(--mc-hairline);
  z-index: 100;
}

.page-title {
  margin: 0;
  font-family: var(--mc-font-display);
  font-size: 20px;
  font-weight: 700;
  color: var(--mc-ink);
  letter-spacing: 0.02em;
}

.header-right {
  display: flex;
  align-items: center;
  gap: 16px;
}

.current-time {
  font-size: 13px;
  color: var(--mc-muted);
  font-variant-numeric: tabular-nums;
}

.user-info {
  display: flex;
  align-items: center;
  gap: 6px;
  font-size: 13px;
  color: var(--mc-ink-soft);
  cursor: pointer;
  padding: 4px 8px;
  border-radius: var(--mc-radius-sm);
  transition: background var(--mc-duration) var(--mc-ease);
}

.user-info:hover {
  background: var(--mc-paper-deep);
}

.main-content {
  padding: 28px;
  overflow-y: auto;
  background: var(--mc-paper);
}
</style>