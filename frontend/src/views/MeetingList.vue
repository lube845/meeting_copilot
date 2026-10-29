<template>
  <div class="meeting-list-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span class="card-title">会议列表</span>
          <el-button type="primary" @click="openUploadDialog">
            <el-icon><Plus /></el-icon>
            新建转写
          </el-button>
        </div>
      </template>

      <!-- 筛选 -->
      <div class="filter-row">
        <el-input
          v-model="filters.keyword"
          placeholder="搜索文件名/主题"
          clearable
          style="width: 240px;"
          @keyup.enter="handleSearch"
          @clear="handleSearch"
        >
          <template #prefix>
            <el-icon><Search /></el-icon>
          </template>
        </el-input>

        <el-select
          v-model="filters.status"
          placeholder="状态筛选"
          clearable
          style="width: 140px;"
          @change="handleSearch"
        >
          <el-option label="已上传" value="uploaded" />
          <el-option label="转写中" value="transcribing" />
          <el-option label="已转写" value="transcribed" />
          <el-option label="已完成" value="ready" />
          <el-option label="失败" value="failed" />
        </el-select>

        <el-date-picker
          v-model="filters.dateRange"
          type="daterange"
          range-separator="至"
          start-placeholder="开始日期"
          end-placeholder="结束日期"
          format="YYYY-MM-DD"
          value-format="YYYY-MM-DD"
          unlink-panels
          :shortcuts="dateShortcuts"
          style="width: 260px;"
          @change="handleSearch"
        />

        <el-button type="primary" @click="handleSearch">
          <el-icon><Search /></el-icon>
          查询
        </el-button>
        <el-button @click="handleReset">
          <el-icon><RefreshCw /></el-icon>
          重置
        </el-button>
      </div>

      <!-- 表格 -->
      <el-table :data="list" stripe v-loading="loading" style="margin-top: 16px;">
        <el-table-column prop="id" label="ID" width="60" />
        <el-table-column prop="file_name" label="文件名" show-overflow-tooltip min-width="180" />
        <el-table-column label="会议主题" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            {{ row.meeting_topic || '—' }}
          </template>
        </el-table-column>
        <el-table-column label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="statusTagType(row.status)" size="small">
              {{ statusLabel(row.status) }}
            </el-tag>
          </template>
        </el-table-column>
        <el-table-column label="创建时间" width="170">
          <template #default="{ row }">
            {{ formatDate(row.created_at) }}
          </template>
        </el-table-column>
        <el-table-column label="操作" width="220" align="center" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="$router.push(`/meetings/${row.id}`)">
              查看
            </el-button>
            <el-button
              v-if="row.meeting_minutes"
              size="small"
              link
              type="success"
              @click="handleDownload(row)"
            >
              下载 Word
            </el-button>
            <el-popconfirm title="确定删除该会议？" @confirm="handleDelete(row)">
              <template #reference>
                <el-button size="small" link type="danger">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
        <template #empty>
          <el-empty description="暂无会议记录" />
        </template>
      </el-table>

      <!-- 分页 -->
      <div class="pagination-wrapper">
        <el-pagination
          v-model:current-page="pagination.page"
          v-model:page-size="pagination.page_size"
          :page-sizes="[10, 20, 50, 100]"
          :total="pagination.total"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="loadData"
          @current-change="loadData"
        />
      </div>
    </el-card>

    <!-- 新建转写弹窗 -->
    <el-dialog
      v-model="uploadDialogVisible"
      title="新建转写"
      width="640px"
      :close-on-click-modal="false"
      :close-on-press-escape="false"
      @close="handleDialogClose"
      destroy-on-close
    >
      <Upload
        ref="uploadRef"
        @completed="handleUploadCompleted"
        @failed="handleUploadFailed"
      />
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, nextTick } from 'vue'
import { useRouter } from 'vue-router'
import { Plus, Search, RefreshCw } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import { formatDate } from '@/utils/timezone'
import { downloadFile } from '@/utils/docx'
import Upload from '@/views/Upload.vue'
import api from '@/api'

const router = useRouter()
const loading = ref(false)
const list = ref([])

const filters = reactive({
  keyword: '',
  status: '',
  dateRange: [],  // [date_from, date_to]
})

const dateShortcuts = [
  {
    text: '今天',
    value: () => {
      const today = new Date()
      return [today, today]
    },
  },
  {
    text: '近 7 天',
    value: () => {
      const today = new Date()
      const start = new Date(today)
      start.setDate(start.getDate() - 6)
      return [start, today]
    },
  },
  {
    text: '近 30 天',
    value: () => {
      const today = new Date()
      const start = new Date(today)
      start.setDate(start.getDate() - 29)
      return [start, today]
    },
  },
  {
    text: '本月',
    value: () => {
      const today = new Date()
      const start = new Date(today.getFullYear(), today.getMonth(), 1)
      return [start, today]
    },
  },
]

const pagination = reactive({
  page: 1,
  page_size: 20,
  total: 0,
})

const uploadDialogVisible = ref(false)
const uploadRef = ref(null)
let lastUploadedMeeting = null

function openUploadDialog() {
  uploadDialogVisible.value = true
}

async function handleUploadCompleted(meeting) {
  lastUploadedMeeting = meeting
  // 关闭弹窗并刷新列表
  uploadDialogVisible.value = false
  await loadData()
  // 转写完成直接进入详情
  router.push(`/meetings/${meeting.id}`)
}

async function handleUploadFailed() {
  // 失败不关闭，让用户在弹窗里看到错误信息；或刷新列表
  await loadData()
}

function handleDialogClose() {
  // 弹窗关闭时清空内部状态
  nextTick(() => {
    uploadRef.value?.resetUpload?.()
  })
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

async function loadData() {
  loading.value = true
  try {
    const params = {
      page: pagination.page,
      page_size: pagination.page_size,
    }
    if (filters.keyword) params.keyword = filters.keyword
    if (filters.status) params.status_filter = filters.status
    if (filters.dateRange && filters.dateRange.length === 2) {
      params.date_from = filters.dateRange[0]
      params.date_to = filters.dateRange[1]
    }

    const res = await api.meeting.list(params)
    list.value = res.items || []
    pagination.total = res.total || 0
  } catch (e) {
    console.error('加载失败', e)
  } finally {
    loading.value = false
  }
}

function handleSearch() {
  pagination.page = 1
  loadData()
}

function handleReset() {
  filters.keyword = ''
  filters.status = ''
  filters.dateRange = []
  pagination.page = 1
  loadData()
}

async function handleDelete(row) {
  try {
    await api.meeting.delete(row.id)
    ElMessage.success('已删除')
    loadData()
  } catch (e) {
    ElMessage.error('删除失败')
  }
}

async function handleDownload(row) {
  try {
    const blob = await api.meeting.exportDocx(row.id)
    const baseName = (row.file_name || `meeting_${row.id}`).replace(/\.[^.]+$/, '')
    downloadFile(blob, `会议纪要_${baseName}.docx`)
  } catch (e) {
    ElMessage.error('下载失败：' + (e?.response?.data?.detail || e.message))
  }
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.meeting-list-page {
  padding: 0;
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
}

.filter-row {
  display: flex;
  gap: 12px;
  align-items: center;
  flex-wrap: wrap;
}

.pagination-wrapper {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}
</style>