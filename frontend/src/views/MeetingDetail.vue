<template>
  <div class="meeting-detail-page" v-loading="loading">
    <!-- 顶部信息条 -->
    <el-card class="info-card" v-if="meeting">
      <el-page-header @back="$router.push('/meetings')">
        <template #content>
          <div class="info-header">
            <span class="file-name">{{ meeting.file_name }}</span>
            <el-tag :type="statusTagType(meeting.status)" size="small">
              {{ statusLabel(meeting.status) }}
            </el-tag>
            <span class="meta-info">
                创建：{{ formatDate(meeting.created_at) }}
              </span>
          </div>
        </template>
      </el-page-header>

      <!-- 后台任务进度条 -->
      <div v-if="task && (task.status === 'running' || task.status === 'pending' || task.status === 'retry')" class="task-progress">
        <el-progress
          :percentage="task.progress || 0"
          :stroke-width="12"
        />
        <p class="task-progress-text">
          {{ task.progress_text || '处理中...' }}
          <span v-if="task.attempts > 1" class="retry-tag">（第 {{ task.attempts }} 次尝试）</span>
        </p>
      </div>

      <!-- 转写/纪要失败提示 + 重试按钮 -->
      <el-alert
        v-if="meeting.status === 'failed' || meeting.status === 'transcribe_failed'"
        :title="meeting.error_message || '处理失败'"
        type="error"
        show-icon
        :closable="false"
        class="error-alert"
      >
        <template #default>
          <div style="margin-top: 8px;">
            <el-button size="small" type="primary" :loading="retrying" @click="handleRetryTranscribe">
              重新转写
            </el-button>
          </div>
        </template>
      </el-alert>
    </el-card>

    <div class="detail-body" v-if="meeting">
      <!-- 左：内容区 -->
      <div class="left-pane">
        <el-card class="content-card">
          <el-tabs v-model="activeTab" class="content-tabs">
            <el-tab-pane label="转写全文" name="transcript">
              <div class="content-area">
                <div v-if="transcript" class="markdown-content" v-html="renderedTranscript" />
                <el-empty v-else-if="meeting.status === 'transcribing' || meeting.status === 'uploaded'" description="正在转写中..." />
                <el-empty v-else description="暂无转写内容" />
              </div>
            </el-tab-pane>
            <el-tab-pane label="会议纪要" name="minutes">
              <div class="content-area">
                <div v-if="meeting.meeting_minutes" class="markdown-content" v-html="renderedMinutes" />
                <el-empty v-else description="尚未生成会议纪要，请在右侧填写信息并点击生成" />
              </div>
            </el-tab-pane>
            <el-tab-pane label="合并预览" name="combined">
              <div class="content-area">
                <div class="markdown-content" v-html="renderedCombined" />
                <el-empty v-if="!transcript && !meeting.meeting_minutes" description="暂无内容" />
              </div>
            </el-tab-pane>
          </el-tabs>
        </el-card>
      </div>

      <!-- 右：信息表单 -->
      <div class="right-pane">
        <el-card>
          <template #header>
            <span class="card-title">会议信息</span>
          </template>

          <el-form :model="form" label-width="84px" label-position="top" size="default">
            <el-form-item label="会议时间" required>
              <el-input v-model="form.meeting_time" placeholder="例如：2025-10-30 14:00" />
            </el-form-item>
            <el-form-item label="会议主题" required>
              <el-input v-model="form.meeting_topic" placeholder="请输入会议主题" />
            </el-form-item>
            <el-form-item label="会议议题">
              <el-input v-model="form.meeting_agenda" type="textarea" :rows="2" placeholder="可选，会议具体议题" />
            </el-form-item>
            <el-form-item label="会议地址">
              <el-input v-model="form.meeting_address" placeholder="可选，会议召开地点或线上会议链接" />
            </el-form-item>

            <el-form-item v-if="meeting.speaker_cnt > 0">
              <template #label>
                <span>参会人员（{{ meeting.speaker_cnt }}人）</span>
              </template>
              <div class="speakers-list">
                <div v-for="i in meeting.speaker_cnt" :key="i" class="speaker-row">
                  <span class="speaker-label">说话人{{ i - 1 }}</span>
                  <el-input
                    v-model="form.speaker_names[i - 1]"
                    placeholder="姓名"
                    size="small"
                    style="flex: 1;"
                  />
                  <el-input
                    v-model="form.speaker_titles[i - 1]"
                    placeholder="职称"
                    size="small"
                    style="flex: 1;"
                  />
                </div>
              </div>
            </el-form-item>

            <el-form-item label="会议纪要模板" required>
              <el-select v-model="form.template_key" placeholder="选择模板" style="width: 100%;">
                <el-option
                  v-for="(content, key) in templates"
                  :key="key"
                  :label="key"
                  :value="key"
                />
              </el-select>
            </el-form-item>

            <el-form-item v-if="form.template_key && templates[form.template_key]">
              <el-input
                :model-value="templates[form.template_key]"
                type="textarea"
                :rows="6"
                readonly
                class="template-preview"
              />
            </el-form-item>

            <el-form-item>
              <el-button
                type="primary"
                :loading="generating"
                :disabled="!canGenerate"
                @click="handleGenerate"
                style="width: 100%;"
              >
                <el-icon><Sparkles /></el-icon>
                生成会议纪要
              </el-button>
            </el-form-item>

            <el-form-item v-if="meeting.meeting_minutes">
              <el-button
                type="success"
                @click="handleDownload"
                style="width: 100%;"
              >
                <el-icon><Download /></el-icon>
                下载 Word
              </el-button>
            </el-form-item>
          </el-form>
        </el-card>
      </div>
    </div>

    <el-empty v-else-if="!loading" description="会议不存在" />
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount, watch } from 'vue'
import { useRoute } from 'vue-router'
import { Sparkles, Download } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { formatDate } from '@/utils/timezone'
import { renderMarkdown } from '@/utils/markdown'
import { downloadFile } from '@/utils/docx'
import api from '@/api'

const route = useRoute()
const meetingId = computed(() => Number(route.params.id))

const loading = ref(false)
const meeting = ref(null)
const transcript = ref('')
const templates = ref({})
const activeTab = ref('transcript')
const generating = ref(false)
const task = ref(null)
const retrying = ref(false)

let taskPollTimer = null

const form = reactive({
  meeting_time: '',
  meeting_topic: '',
  meeting_agenda: '',
  meeting_address: '',
  speaker_names: [],
  speaker_titles: [],
  template_key: '',
})

function statusLabel(s) {
  const m = {
    uploading: '上传中',
    uploaded: '已上传',
    upload_failed: '上传失败',
    transcribing: '转写中',
    transcribed: '已转写',
    transcribe_failed: '转写失败',
    ready: '已完成',
  }
  return m[s] || s || '未知'
}

function statusTagType(s) {
  if (s === 'ready' || s === 'transcribed') return 'success'
  if (s === 'failed' || s === 'transcribe_failed' || s === 'upload_failed') return 'danger'
  if (s === 'transcribing' || s === 'uploading') return 'warning'
  return 'info'
}

const renderedTranscript = computed(() =>
  transcript.value ? renderMarkdown(transcript.value) : ''
)
const renderedMinutes = computed(() =>
  meeting.value?.meeting_minutes ? renderMarkdown(meeting.value.meeting_minutes) : ''
)
const renderedCombined = computed(() => {
  const m = meeting.value
  if (!m) return ''
  const parts = []
  if (m.meeting_minutes) parts.push(`# 会议纪要\n\n${m.meeting_minutes}`)
  if (transcript.value) parts.push(`# 转写全文\n\n${transcript.value}`)
  return parts.length ? renderMarkdown(parts.join('\n\n---\n\n')) : ''
})

const canGenerate = computed(() => {
  return Boolean(form.meeting_time && form.meeting_topic && form.template_key && transcript.value)
})

async function loadData() {
  loading.value = true
  try {
    meeting.value = await api.meeting.get(meetingId.value)

    // 同步已填字段
    if (meeting.value.meeting_time) form.meeting_time = meeting.value.meeting_time
    if (meeting.value.meeting_topic) form.meeting_topic = meeting.value.meeting_topic
    if (meeting.value.meeting_agenda) form.meeting_agenda = meeting.value.meeting_agenda
    if (meeting.value.meeting_address) form.meeting_address = meeting.value.meeting_address
    if (meeting.value.speaker_names) form.speaker_names = [...meeting.value.speaker_names]
    if (meeting.value.speaker_titles) form.speaker_titles = [...meeting.value.speaker_titles]
    if (meeting.value.template_key) form.template_key = meeting.value.template_key

    // 拉取转写
    try {
      const tr = await api.transcript.get(meetingId.value)
      transcript.value = tr.transcript_markdown || ''
    } catch (e) {
      console.error('加载转写失败', e)
    }

    // 若当前处于转写中，自动启动任务轮询
    const s = meeting.value.status
    if (s === 'transcribing' || s === 'uploaded') {
      // 先取一下 task 状态，如果还有 PENDING/RUNNING/RETRY 才轮询
      try {
        const t = await api.meeting.getTask(meetingId.value)
        task.value = t
        if (t && (t.status === 'pending' || t.status === 'running' || t.status === 'retry')) {
          startTaskPolling()
        }
      } catch {}
    }
  } catch (e) {
    console.error('加载会议失败', e)
    ElMessage.error('会议不存在或加载失败')
  } finally {
    loading.value = false
  }
}

async function loadTemplates() {
  try {
    const res = await api.settings.getTemplates()
    templates.value = res.templates || {}
    if (!form.template_key) {
      const keys = Object.keys(templates.value)
      if (keys.length) form.template_key = keys[0]
    }
  } catch (e) {
    console.error('加载模板失败', e)
  }
}

async function handleGenerate() {
  if (!canGenerate.value) {
    ElMessage.warning('请填写会议时间、主题并选择模板')
    return
  }
  generating.value = true
  try {
    await api.meeting.generateMinutes(meetingId.value, {
      meeting_time: form.meeting_time,
      meeting_topic: form.meeting_topic,
      meeting_agenda: form.meeting_agenda,
      meeting_address: form.meeting_address,
      speaker_names: form.speaker_names,
      speaker_titles: form.speaker_titles,
      template_key: form.template_key,
    })
    ElMessage.info('已入队，开始生成会议纪要...')
    activeTab.value = 'minutes'
    startTaskPolling()
  } catch (e) {
    ElMessage.error('入队失败：' + (e?.response?.data?.detail || e.message))
  } finally {
    generating.value = false
  }
}

async function handleRetryTranscribe() {
  retrying.value = true
  try {
    // 复用 upload 文件重新入队：先看 meeting 是否还有 oss_object_key
    if (!meeting.value?.oss_object_key) {
      ElMessage.error('音频文件已丢失，请重新上传')
      return
    }
    await api.meeting.generateMinutes(meetingId.value, {
      meeting_time: form.meeting_time || meeting.value.meeting_time || '',
      meeting_topic: form.meeting_topic || meeting.value.meeting_topic || '',
      meeting_agenda: form.meeting_agenda || meeting.value.meeting_agenda || '',
      meeting_address: form.meeting_address || meeting.value.meeting_address || '',
      speaker_names: form.speaker_names.length ? form.speaker_names : (meeting.value.speaker_names || []),
      speaker_titles: form.speaker_titles.length ? form.speaker_titles : (meeting.value.speaker_titles || []),
      template_key: form.template_key || meeting.value.template_key || '标准会议纪要',
    })
    ElMessage.success('已重新提交')
    startTaskPolling()
  } catch (e) {
    ElMessage.error('重试失败：' + (e?.response?.data?.detail || e.message))
  } finally {
    retrying.value = false
  }
}

async function handleDownload() {
  try {
    const blob = await api.meeting.exportDocx(meetingId.value)
    const baseName = (meeting.value.file_name || 'meeting').replace(/\.[^.]+$/, '')
    downloadFile(blob, `会议纪要_${baseName}.docx`)
  } catch (e) {
    ElMessage.error('下载失败：' + (e?.response?.data?.detail || e.message))
  }
}

function startTaskPolling() {
  stopTaskPolling()
  let ticks = 0
  const MAX_TICKS = 300  // 2s × 300 = 10 分钟上限
  taskPollTimer = setInterval(async () => {
    ticks++
    try {
      const [t, m] = await Promise.all([
        api.meeting.getTask(meetingId.value).catch(() => null),
        api.meeting.get(meetingId.value),
      ])
      task.value = t
      meeting.value = m
      // 任务完成（成功或失败）→ 停轮询
      if (t && (t.status === 'success' || t.status === 'failed')) {
        if (t.status === 'success') {
          ElMessage.success('会议纪要生成完成！')
          activeTab.value = 'minutes'
        } else {
          ElMessage.error('生成失败：' + (t.error_message || ''))
        }
        stopTaskPolling()
        // 重新拉一次完整数据
        loadData()
      }
    } catch (e) {
      console.error('task poll error', e)
    }
    if (ticks >= MAX_TICKS) {
      stopTaskPolling()
      ElMessage.warning('生成超时，请稍后查看')
    }
  }, 2000)
}

function stopTaskPolling() {
  if (taskPollTimer) {
    clearInterval(taskPollTimer)
    taskPollTimer = null
  }
}

watch(meetingId, () => {
  loadData()
})

onMounted(() => {
  loadData()
  loadTemplates()
  // 如果一进来就处于转写中，自动启动轮询
  // （先拉一次状态由 loadData 完成）
})

onBeforeUnmount(() => {
  stopTaskPolling()
})
</script>

<style scoped>
.meeting-detail-page {
  padding: 0;
}

.info-card {
  margin-bottom: 16px;
}

.task-progress {
  margin-top: 16px;
}

.task-progress-text {
  margin-top: 6px;
  margin-bottom: 0;
  color: var(--mc-muted);
  font-size: 13px;
}

.retry-tag {
  margin-left: 8px;
  padding: 1px 6px;
  border-radius: 3px;
  background: rgba(245, 158, 11, 0.12);
  color: #b45309;
  font-size: 11px;
}

.info-header {
  display: flex;
  align-items: center;
  gap: 16px;
}

.file-name {
  font-family: var(--mc-font-display);
  font-size: 18px;
  font-weight: 700;
  color: var(--mc-ink);
}

.meta-info {
  font-size: 13px;
  color: var(--mc-muted);
}

.detail-body {
  display: grid;
  grid-template-columns: 2fr 1fr;
  gap: 16px;
}

.left-pane,
.right-pane {
  min-width: 0;
}

.content-card {
  height: 100%;
}

.content-area {
  padding: 16px;
  min-height: 480px;
  max-height: 70vh;
  overflow-y: auto;
  background: var(--mc-paper);
  border-radius: var(--mc-radius-sm);
  border: 1px solid var(--mc-hairline);
}

.markdown-content {
  font-size: 14px;
  line-height: 1.8;
  color: var(--mc-ink);
}

.markdown-content :deep(h1),
.markdown-content :deep(h2),
.markdown-content :deep(h3) {
  margin-top: 16px;
  margin-bottom: 12px;
  font-family: var(--mc-font-display);
  font-weight: 700;
}

.markdown-content :deep(pre) {
  background: var(--mc-paper-deep);
  padding: 12px;
  border-radius: var(--mc-radius-sm);
  overflow-x: auto;
}

.markdown-content :deep(code) {
  background: var(--mc-paper-deep);
  padding: 2px 6px;
  border-radius: 3px;
  font-size: 13px;
}

.card-title {
  font-family: var(--mc-font-display);
  font-weight: 700;
  font-size: 15px;
  color: var(--mc-ink);
}

.speakers-list {
  display: flex;
  flex-direction: column;
  gap: 8px;
  width: 100%;
}

.speaker-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.speaker-label {
  font-size: 13px;
  color: var(--mc-muted);
  min-width: 56px;
}

.template-preview :deep(textarea) {
  font-family: 'SF Mono', 'Consolas', monospace;
  font-size: 12px;
  color: var(--mc-muted);
}
</style>