<template>
  <div class="change-password-page">
    <div class="cp-box">
      <div class="brand">
        <KeyRound :size="26" class="brand-icon" />
        <h1 class="title">修改密码</h1>
        <p v-if="forced" class="subtitle warning">首次登录或密码已重置，请先修改密码</p>
        <p v-else class="subtitle">设置新的登录密码</p>
      </div>
      <el-form ref="formRef" :model="form" :rules="rules" class="cp-form">
        <el-form-item prop="old_password" label="当前密码">
          <el-input
            v-model="form.old_password"
            type="password"
            show-password
            placeholder="当前密码"
            size="large"
            :prefix-icon="Lock"
          />
        </el-form-item>
        <el-form-item prop="new_password" label="新密码">
          <el-input
            v-model="form.new_password"
            type="password"
            show-password
            placeholder="新密码（至少 6 位）"
            size="large"
            :prefix-icon="Lock"
          />
        </el-form-item>
        <el-form-item prop="confirm" label="确认新密码">
          <el-input
            v-model="form.confirm"
            type="password"
            show-password
            placeholder="再输入一次新密码"
            size="large"
            :prefix-icon="Lock"
          />
        </el-form-item>
        <el-form-item>
          <el-button
            type="primary"
            size="large"
            :loading="loading"
            class="cp-button"
            @click="handleSubmit"
          >
            确认修改
          </el-button>
        </el-form-item>
        <el-form-item v-if="!forced">
          <el-button link @click="$router.back()">返回</el-button>
        </el-form-item>
      </el-form>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { Lock, KeyRound } from 'lucide-vue-next'
import { setAuthSession, clearAuthSession, getUserInfo } from '@/utils/auth'
import api from '@/api'

const route = useRoute()
const router = useRouter()
const formRef = ref(null)
const loading = ref(false)
const forced = computed(() => route.query.forced === '1')

const form = reactive({
  old_password: '',
  new_password: '',
  confirm: '',
})

const rules = {
  old_password: [{ required: true, message: '请输入当前密码', trigger: 'blur' }],
  new_password: [
    { required: true, message: '请输入新密码', trigger: 'blur' },
    { min: 6, message: '新密码长度至少 6 位', trigger: 'blur' },
  ],
  confirm: [
    { required: true, message: '请再次输入新密码', trigger: 'blur' },
    {
      validator: (_rule, value, cb) => {
        if (value !== form.new_password) cb(new Error('两次输入的密码不一致'))
        else cb()
      },
      trigger: 'blur',
    },
  ],
}

async function handleSubmit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  loading.value = true
  try {
    const res = await api.auth.changePassword({
      old_password: form.old_password,
      new_password: form.new_password,
    })
    if (!res.success) {
      ElMessage.error(res.message || '修改失败')
      return
    }
    ElMessage.success('密码已修改，请重新登录')
    // 改密成功后服务端仍然有效，但强制改密已解除 → 清掉旧 session，要求重新登录
    clearAuthSession()
    router.push('/login')
  } catch (e) {
    if (e === 'cancel' || e === 'close') return
    ElMessage.error(e?.response?.data?.detail || '修改失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.change-password-page {
  display: flex;
  align-items: center;
  justify-content: center;
  min-height: 100vh;
  background: var(--mc-paper);
  background-image:
    linear-gradient(var(--mc-hairline) 1px, transparent 1px),
    linear-gradient(90deg, var(--mc-hairline) 1px, transparent 1px);
  background-size: 56px 56px;
  background-position: center;
  position: relative;
}
.change-password-page::before {
  content: '';
  position: absolute;
  inset: 0;
  background: radial-gradient(ellipse 70% 60% at 50% 45%, var(--mc-paper) 30%, transparent 75%);
  pointer-events: none;
}
.cp-box {
  position: relative;
  width: 440px;
  padding: 40px 36px 32px;
  background: #fff;
  border: 1px solid var(--mc-hairline);
  border-radius: var(--mc-radius-md);
  box-shadow: 0 2px 6px rgba(33, 29, 24, 0.05), 0 16px 48px rgba(33, 29, 24, 0.07);
}
.cp-box::before {
  content: '';
  position: absolute;
  top: -1px;
  left: 32px;
  right: 32px;
  height: 2px;
  background: var(--mc-accent);
}
.brand { text-align: center; margin-bottom: 24px; }
.brand-icon { color: var(--mc-accent); }
.title { margin: 12px 0 6px; font-family: var(--mc-font-display); font-size: 22px; font-weight: 700; color: var(--mc-ink); letter-spacing: 0.05em; }
.subtitle { margin: 0; font-size: 12.5px; color: var(--mc-muted); letter-spacing: 0.04em; }
.subtitle.warning { color: #b45309; }
.cp-form { margin-top: 8px; }
.cp-button { width: 100%; letter-spacing: 0.3em; text-indent: 0.3em; font-weight: 600; }
</style>