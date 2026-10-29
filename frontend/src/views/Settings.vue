<template>
  <div class="settings-page" v-loading="loading">
    <!-- LLM 配置 -->
    <el-card class="settings-card">
      <template #header>
        <div class="card-header">
          <span class="card-title">
            <el-icon><Bot /></el-icon>
            LLM 配置
          </span>
          <el-tag size="small">用于生成会议纪要</el-tag>
        </div>
      </template>

      <el-form :model="llmForm" label-width="120px" size="default">
        <el-form-item label="API 地址">
          <el-input v-model="llmForm.api_endpoint" placeholder="例如：http://host:port/v1/chat/completions" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="llmForm.api_key"
            type="password"
            show-password
            placeholder="留空表示不发送 Authorization"
          />
        </el-form-item>
        <el-form-item label="模型">
          <el-input v-model="llmForm.model" placeholder="例如：Qwen3-32B" />
        </el-form-item>
        <el-form-item label="温度">
          <el-input-number v-model="llmForm.temperature" :min="0" :max="2" :step="0.1" />
        </el-form-item>
        <el-form-item label="最大 Tokens">
          <el-input-number v-model="llmForm.max_tokens" :min="256" :max="32768" :step="512" />
        </el-form-item>
        <el-form-item label="思考模式">
          <el-switch v-model="llmForm.enable_thinking" />
          <span class="form-tip">开启后模型先输出思考过程</span>
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="savingLlm" @click="handleSaveLlm">
            <el-icon><Save /></el-icon>
            保存 LLM 配置
          </el-button>
          <el-button :loading="testingLlm" @click="handleTestLlm">
            <el-icon><Plug /></el-icon>
            测试连接
          </el-button>
        </el-form-item>
        <el-form-item v-if="llmTestResult">
          <el-alert
            :type="llmTestResult.success ? 'success' : 'error'"
            :title="llmTestResult.message"
            :description="llmTestResult.success ? `耗时 ${llmTestResult.elapsed_ms} ms，预览：${llmTestResult.reply_preview}` : ''"
            :closable="false"
            show-icon
          />
        </el-form-item>
      </el-form>
    </el-card>

    <!-- ASR 配置 -->
    <el-card class="settings-card">
      <template #header>
        <div class="card-header">
          <span class="card-title">
            <el-icon><Mic /></el-icon>
            ASR 配置
          </span>
          <el-tag size="small" type="info">内置 FunASR 时通常无需修改</el-tag>
        </div>
      </template>

      <el-form :model="asrForm" label-width="120px" size="default">
        <el-form-item label="ASR API URL">
          <el-input v-model="asrForm.api_url" placeholder="可选 - 远程 ASR 服务的 base URL" />
        </el-form-item>
        <el-form-item label="API Key">
          <el-input
            v-model="asrForm.api_key"
            type="password"
            show-password
            placeholder="可选"
          />
        </el-form-item>
        <el-form-item>
          <el-button type="primary" :loading="savingAsr" @click="handleSaveAsr">
            <el-icon><Save /></el-icon>
            保存 ASR 配置
          </el-button>
          <el-button :loading="testingAsr" @click="handleTestAsr">
            <el-icon><Plug /></el-icon>
            测试连接
          </el-button>
        </el-form-item>
        <el-form-item v-if="asrTestResult">
          <el-alert
            :type="asrTestResult.success ? 'success' : 'error'"
            :title="asrTestResult.message"
            :closable="false"
            show-icon
          />
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { Bot, Mic, Save, Plug } from 'lucide-vue-next'
import api from '@/api'

const loading = ref(false)

const llmForm = reactive({
  api_endpoint: '',
  api_key: '',
  model: '',
  temperature: 0.1,
  max_tokens: 16384,
  enable_thinking: false,
})

const asrForm = reactive({
  api_url: '',
  api_key: '',
})

const savingLlm = ref(false)
const testingLlm = ref(false)
const llmTestResult = ref(null)

const savingAsr = ref(false)
const testingAsr = ref(false)
const asrTestResult = ref(null)

async function loadData() {
  loading.value = true
  try {
    const [llm, asr] = await Promise.all([
      api.settings.getLlm(),
      api.settings.getAsr(),
    ])
    Object.assign(llmForm, {
      api_endpoint: llm.api_endpoint || '',
      api_key: llm.api_key || '',
      model: llm.model || '',
      temperature: llm.temperature ?? 0.1,
      max_tokens: llm.max_tokens ?? 16384,
      enable_thinking: !!llm.enable_thinking,
    })
    Object.assign(asrForm, {
      api_url: asr.api_url || '',
      api_key: asr.api_key || '',
    })
  } catch (e) {
    console.error('加载配置失败', e)
  } finally {
    loading.value = false
  }
}

async function handleSaveLlm() {
  savingLlm.value = true
  try {
    await api.settings.updateLlm({
      api_endpoint: llmForm.api_endpoint,
      api_key: llmForm.api_key,
      model: llmForm.model,
      temperature: llmForm.temperature,
      max_tokens: llmForm.max_tokens,
      enable_thinking: llmForm.enable_thinking,
    })
    ElMessage.success('LLM 配置已保存')
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    savingLlm.value = false
  }
}

async function handleTestLlm() {
  testingLlm.value = true
  llmTestResult.value = null
  try {
    llmTestResult.value = await api.settings.testLlm({
      api_endpoint: llmForm.api_endpoint,
      api_key: llmForm.api_key,
      model: llmForm.model,
      temperature: llmForm.temperature,
    })
  } catch (e) {
    llmTestResult.value = { success: false, message: e?.response?.data?.detail || e.message }
  } finally {
    testingLlm.value = false
  }
}

async function handleSaveAsr() {
  savingAsr.value = true
  try {
    await api.settings.updateAsr({
      api_url: asrForm.api_url,
      api_key: asrForm.api_key,
    })
    ElMessage.success('ASR 配置已保存')
  } catch (e) {
    ElMessage.error('保存失败')
  } finally {
    savingAsr.value = false
  }
}

async function handleTestAsr() {
  testingAsr.value = true
  asrTestResult.value = null
  try {
    asrTestResult.value = await api.settings.testAsr({
      api_url: asrForm.api_url,
    })
  } catch (e) {
    asrTestResult.value = { success: false, message: e?.response?.data?.detail || e.message }
  } finally {
    testingAsr.value = false
  }
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.settings-page {
  max-width: 800px;
  margin: 0 auto;
}

.settings-card {
  margin-bottom: 20px;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-title {
  font-family: var(--mc-font-display);
  font-weight: 700;
  font-size: 16px;
  color: var(--mc-ink);
  display: flex;
  align-items: center;
  gap: 8px;
}

.form-tip {
  margin-left: 12px;
  font-size: 12px;
  color: var(--mc-muted);
}
</style>