<template>
  <div class="home-page">
    <!-- 统计卡片 -->
    <el-row :gutter="20" class="stat-row">
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-info">
              <div class="stat-label">总会议数</div>
              <div class="stat-value mc-nums">{{ stats.total }}</div>
            </div>
            <FileText :size="22" class="stat-icon" />
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-info">
              <div class="stat-label">已生成纪要</div>
              <div class="stat-value mc-nums">{{ stats.ready }}</div>
            </div>
            <FileCheck :size="22" class="stat-icon" />
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card">
          <div class="stat-content">
            <div class="stat-info">
              <div class="stat-label">总说话人次</div>
              <div class="stat-value mc-nums">{{ stats.speakers }}</div>
            </div>
            <Users :size="22" class="stat-icon" />
          </div>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card class="stat-card stat-card-accent">
          <div class="stat-content">
            <div class="stat-info">
              <div class="stat-label">转写失败</div>
              <div class="stat-value accent mc-nums">{{ stats.failed }}</div>
            </div>
            <TriangleAlert :size="22" class="stat-icon accent" />
          </div>
        </el-card>
      </el-col>
    </el-row>

    <!-- 最近会议 -->
    <el-row :gutter="20" class="recent-row">
      <el-col :span="24">
        <el-card>
          <template #header>
            <div class="card-header">
              <span class="card-title">最近会议</span>
              <el-button text @click="$router.push('/meetings')">
                查看全部
                <el-icon><ArrowRight /></el-icon>
              </el-button>
            </div>
          </template>
          <el-table :data="recent" stripe v-loading="loading">
            <el-table-column prop="id" label="ID" width="60" />
            <el-table-column prop="file_name" label="文件名" show-overflow-tooltip />
            <el-table-column prop="meeting_topic" label="会议主题" show-overflow-tooltip>
              <template #default="{ row }">
                {{ row.meeting_topic || '—' }}
              </template>
            </el-table-column>
            <el-table-column label="状态" width="120">
              <template #default="{ row }">
                <el-tag :type="statusTagType(row.status)" size="small">
                  {{ statusLabel(row.status) }}
                </el-tag>
              </template>
            </el-table-column>
            <el-table-column label="说话人" width="80" align="center">
              <template #default="{ row }">
                {{ row.speaker_cnt || 0 }}
              </template>
            </el-table-column>
            <el-table-column label="创建时间" width="170">
              <template #default="{ row }">
                {{ formatDate(row.created_at) }}
              </template>
            </el-table-column>
            <el-table-column label="操作" width="100" align="center">
              <template #default="{ row }">
                <el-button size="small" link type="primary" @click="$router.push(`/meetings/${row.id}`)">
                  查看
                </el-button>
              </template>
            </el-table-column>
            <template #empty>
              <el-empty description="暂无会议记录" />
            </template>
          </el-table>
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { FileText, FileCheck, Users, TriangleAlert, ArrowRight } from 'lucide-vue-next'
import { formatDate } from '@/utils/timezone'
import api from '@/api'

const stats = reactive({ total: 0, ready: 0, speakers: 0, failed: 0 })
const recent = ref([])
const loading = ref(false)

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
    const res = await api.meeting.list({ page: 1, page_size: 5 })
    recent.value = res.items || []
    stats.total = res.total || 0

    // 简单遍历统计（量级小到分页全部拉一次也行，先用前 100 条做近似）
    const fullRes = await api.meeting.list({ page: 1, page_size: 100 })
    const all = fullRes.items || []
    stats.ready = all.filter(x => x.status === 'ready').length
    stats.failed = all.filter(x =>
      ['failed', 'transcribe_failed', 'upload_failed'].includes(x.status)
    ).length
    stats.speakers = all.reduce((sum, x) => sum + (x.speaker_cnt || 0), 0)
  } catch (e) {
    console.error('加载失败', e)
  } finally {
    loading.value = false
  }
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.home-page {
  padding: 0;
}

.stat-row {
  margin-bottom: 20px;
}

.stat-card {
  transition: border-color var(--mc-duration) var(--mc-ease);
}

.stat-card:hover {
  border-color: var(--mc-hairline-dark);
}

.stat-card-accent {
  border-top: 2px solid var(--mc-accent);
}

.stat-content {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  padding: 4px 0;
}

.stat-icon {
  color: var(--mc-muted);
  margin-top: 2px;
  flex-shrink: 0;
}

.stat-icon.accent {
  color: var(--mc-accent);
}

.stat-info {
  flex: 1;
}

.stat-value {
  font-family: var(--mc-font-display);
  font-size: 34px;
  font-weight: 700;
  color: var(--mc-ink);
  font-variant-numeric: tabular-nums;
  line-height: 1.2;
  margin-top: 6px;
}

.stat-value.accent {
  color: var(--mc-accent);
}

.stat-label {
  font-size: 12.5px;
  color: var(--mc-muted);
  letter-spacing: 0.06em;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.card-title {
  font-family: var(--mc-font-display);
  font-weight: 700;
  font-size: 15.5px;
  color: var(--mc-ink);
}
</style>