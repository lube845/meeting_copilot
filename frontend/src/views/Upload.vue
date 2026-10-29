<template>
  <div class="upload-component">
    <el-upload
      ref="uploadRef"
      class="upload-area"
      drag
      :auto-upload="false"
      :limit="1"
      :on-change="handleFileChange"
      :on-exceed="handleExceed"
      accept=".wav,.mp3,.mp4,.m4a,.flac,.ogg,.webm,.amr"
      v-model:file-list="fileList"
    >
      <el-icon class="upload-icon"><Upload /></el-icon>
      <div class="upload-text">
        点击或拖拽文件到此处上传
      </div>
      <template #tip>
        <div class="upload-tip">
          支持 wav / mp3 / mp4 / m4a / flac / ogg / webm / amr 格式，单文件不超过 500MB
        </div>
      </template>
    </el-upload>

    <div class="actions" v-if="fileList.length && !currentMeeting">
      <el-button type="primary" :loading="uploading" @click="handleStartUpload">
        <el-icon><Upload /></el-icon>
        开始上传转写
      </el-button>
      <el-button @click="resetUpload" plain>清空</el-button>
    </div>

    <el-card v-if="currentMeeting" class="progress-card" shadow="never">
      <el-descriptions :column="2" border size="small">
        <el-descriptions-item label="文件名">{{ currentMeeting.file_name }}</el-descriptions-item>
        <el-descriptions-item label="大小">
          {{ formatFileSize(currentMeeting.file_size) }}
        </el-descriptions-item>
        <el-descriptions-item label="状态">
          <el-tag :type="statusTagType(currentMeeting.status)" size="small">
            {{ statusLabel(currentMeeting.status) }}
          </el-tag>
        </el-descriptions-item>
        <el-descriptions-item label="说话人数">
          {{ currentMeeting.speaker_cnt || '—' }}
        </el-descriptions-item>
      </el-descriptions>

      <div class="progress-info" v-if="polling">
        <el-progress
          :percentage="realProgress"
          :status="realProgress >= 100 ? 'success' : (taskFailed ? 'exception' : undefined)"
          :stroke-width="14"
        />
        <p class="progress-text">
          {{ progressText }}
          <span v-if="task && task.attempts > 1" class="retry-tag">
            （第 {{ task.attempts }} 次尝试）
          </span>
        </p>
      </div>

      <el-alert
        v-if="currentMeeting.status === 'failed' || currentMeeting.status === 'transcribe_failed'"
        :title="currentMeeting.error_message || '处理失败'"
        type="error"
        show-icon
        :closable="false"
        class="error-alert"
      />
    </el-card>
  </div>
</template>

<script setup>
import { ref, computed, onBeforeUnmount } from 'vue'
import { Upload } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import api from '@/api'

const emit = defineEmits(['completed', 'failed'])

const uploadRef = ref(null)
const fileList = ref([])
const uploading = ref(false)
const currentMeeting = ref(null)
const polling = ref(false)
const progressText = ref('正在处理...')
const task = ref(null)
const realProgress = ref(0)
const taskFailed = ref(false)

let pollTimer = null

const ACCEPT_FORMATS = ['wav', 'mp3', 'mp4', 'm4a', 'flac', 'ogg', 'webm', 'amr']

function fileExt(name) {
  if (!name) return ''
  const i = name.lastIndexOf('.')
  return i >= 0 ? name.slice(i + 1).toLowerCase() : ''
}

function formatFileSize(bytes) {
  if (!bytes) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  let i = 0
  let v = bytes
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024
    i++
  }
  return `${v.toFixed(2)} ${units[i]}`
}

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

function isDoneStatus(s) {
  return ['transcribed', 'ready', 'failed', 'transcribe_failed'].includes(s)
}

function handleFileChange(file, list) {
  fileList.value = list.slice(-1)
  if (!file.raw) return
  const ext = fileExt(file.name)
  if (!ACCEPT_FORMATS.includes(ext)) {
    ElMessage.error(`不支持的格式 .${ext}`)
    fileList.value = []
  }
}

function handleExceed() {
  ElMessage.warning('只能上传一个文件，请先清空再选')
}

async function handleStartUpload() {
  if (!fileList.value.length || !fileList.value[0].raw) {
    ElMessage.warning('请先选择文件')
    return
  }
  uploading.value = true
  try {
    const file = fileList.value[0].raw
    const ext = fileExt(file.name)

    progressText.value = '正在初始化上传...'
    const init = await api.meeting.initUpload({
      file_name: file.name,
      file_size: file.size,
      file_type: ext,
    })

    currentMeeting.value = await api.meeting.get(init.meeting_id)

    progressText.value = '正在上传文件到 MinIO...'
    const fd = new FormData()
    fd.append('upload_file', file)
    const res = await api.meeting.upload(init.meeting_id, fd)

    // 服务端可能命中同 MD5 复用旧记录，此时 meeting_id 与新上传不同
    if (res?.status === 'duplicate' || res?.meeting_id !== init.meeting_id) {
      ElMessage.info('检测到重复文件，复用已有记录')
      currentMeeting.value = await api.meeting.get(res.meeting_id)
    }

    progressText.value = '正在转写音频...'
    startPolling(res.meeting_id || init.meeting_id)
  } catch (e) {
    ElMessage.error('上传失败：' + (e?.response?.data?.detail || e.message))
    emit('failed', e)
  } finally {
    uploading.value = false
  }
}

function startPolling(meetingId) {
  polling.value = true
  taskFailed.value = false
  realProgress.value = 0
  task.value = null
  let ticks = 0
  const MAX_TICKS = 600  // 2s 一次，最多 20 分钟

  pollTimer = setInterval(async () => {
    ticks++
    try {
      // 同时拉 meeting 状态 + 任务进度
      const [m, t] = await Promise.all([
        api.meeting.get(meetingId),
        api.meeting.getTask(meetingId).catch(() => null),
      ])
      currentMeeting.value = m
      if (t) {
        task.value = t
        realProgress.value = t.progress || 0
        taskFailed.value = t.status === 'failed'
        if (t.status === 'running' || t.status === 'pending' || t.status === 'retry') {
          progressText.value = t.progress_text || '处理中...'
        }
      }
      if (isDoneStatus(m.status)) {
        stopPolling()
        if (m.status === 'failed' || m.status === 'transcribe_failed') {
          ElMessage.error('转写失败：' + (m.error_message || ''))
          emit('failed', m)
        } else {
          ElMessage.success('转写完成！')
          emit('completed', m)
        }
      }
    } catch (e) {
      console.error('轮询失败', e)
    }
    if (ticks >= MAX_TICKS) {
      stopPolling()
      ElMessage.warning('转写超时，请稍后到会议列表查看')
    }
  }, 2000)
}

function stopPolling() {
  if (pollTimer) {
    clearInterval(pollTimer)
    pollTimer = null
  }
  polling.value = false
}

function resetUpload() {
  stopPolling()
  uploadRef.value?.clearFiles?.()
  fileList.value = []
  currentMeeting.value = null
  task.value = null
  realProgress.value = 0
  taskFailed.value = false
  progressText.value = '正在处理...'
}

defineExpose({ resetUpload })

onBeforeUnmount(() => {
  stopPolling()
})
</script>

<style scoped>
.upload-component {
  width: 100%;
}

.upload-area {
  width: 100%;
}

.upload-area :deep(.el-upload-dragger) {
  padding: 40px 20px;
}

.upload-icon {
  font-size: 48px;
  color: var(--mc-muted);
  margin-bottom: 12px;
}

.upload-text {
  font-size: 15px;
  color: var(--mc-ink-soft);
  margin-bottom: 8px;
}

.upload-tip {
  font-size: 12px;
  color: var(--mc-muted);
  margin-top: 8px;
}

.actions {
  display: flex;
  gap: 12px;
  margin-top: 16px;
}

.progress-card {
  margin-top: 16px;
}

.progress-info {
  margin-top: 16px;
}

.progress-text {
  margin-top: 8px;
  color: var(--mc-muted);
  font-size: 13px;
  text-align: center;
}

.retry-tag {
  margin-left: 8px;
  padding: 1px 6px;
  border-radius: 3px;
  background: rgba(245, 158, 11, 0.12);
  color: #b45309;
  font-size: 11px;
}

.error-alert {
  margin-top: 16px;
}
</style>