<template>
  <div class="audit-logs-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span class="card-title">审计日志</span>
          <div class="header-actions">
            <el-button @click="loadData" :loading="loading">
              <el-icon><RefreshCw /></el-icon>
              刷新
            </el-button>
            <el-button type="primary" @click="handleExport" :loading="exporting">
              <el-icon><Download /></el-icon>
              导出 CSV
            </el-button>
          </div>
        </div>
      </template>

      <!-- 筛选条 -->
      <div class="filter-row">
        <el-input
          v-model="filters.keyword"
          placeholder="搜索操作人/姓名/对象描述"
          clearable
          style="width: 220px;"
          @keyup.enter="handleSearch"
        >
          <template #prefix><el-icon><Search /></el-icon></template>
        </el-input>

        <el-select
          v-model="filters.actor_loginid"
          placeholder="操作人"
          clearable filterable
          style="width: 160px;"
          @change="handleSearch"
        >
          <el-option
            v-for="a in actors"
            :key="a.loginid"
            :label="`${a.name || a.loginid}（${a.count}）`"
            :value="a.loginid"
          />
        </el-select>

        <el-select
          v-model="filters.action"
          placeholder="动作（支持前缀）"
          clearable filterable
          style="width: 200px;"
          @change="handleSearch"
        >
          <el-option
            v-for="a in actions"
            :key="a.action"
            :label="`${a.action}（${a.count}）`"
            :value="a.action"
          />
        </el-select>

        <el-date-picker
          v-model="filters.dateRange"
          type="datetimerange"
          range-separator="至"
          start-placeholder="开始时间"
          end-placeholder="结束时间"
          format="YYYY-MM-DD HH:mm:ss"
          value-format="YYYY-MM-DDTHH:mm:ss"
          @change="handleSearch"
        />

        <el-tooltip content="默认只看写操作；打开后包含页面访问（page.view）等噪音日志">
          <el-checkbox v-model="filters.writeOnly" @change="handleSearch">
            只看写操作
          </el-checkbox>
        </el-tooltip>

        <el-button @click="handleReset">重置</el-button>
      </div>

      <!-- 表格 -->
      <el-table :data="items" v-loading="loading" stripe class="audit-table">
        <el-table-column prop="created_at" label="时间" width="170">
          <template #default="{ row }">
            <span class="time-text">{{ formatTime(row.created_at) }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="actor_loginid" label="操作人" width="120">
          <template #default="{ row }">
            <span class="actor-text">{{ row.actor_name || row.actor_loginid }}</span>
            <span class="actor-loginid">@{{ row.actor_loginid }}</span>
          </template>
        </el-table-column>
        <el-table-column prop="actor_role" label="角色" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.actor_role === 'admin'" type="danger" size="small">管理员</el-tag>
            <el-tag v-else-if="row.actor_role" type="info" size="small">{{ row.actor_role }}</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="action" label="动作" width="200">
          <template #default="{ row }">
            <code class="action-code">{{ row.action }}</code>
          </template>
        </el-table-column>
        <el-table-column prop="target_label" label="对象" min-width="180">
          <template #default="{ row }">
            <span v-if="row.target_label">{{ row.target_label }}</span>
            <span v-else-if="row.target_id" class="muted">#{{ row.target_id }}</span>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="result" label="结果" width="80">
          <template #default="{ row }">
            <el-tag v-if="row.result === 'success'" type="success" size="small">成功</el-tag>
            <el-tag v-else-if="row.result === 'fail'" type="danger" size="small">失败</el-tag>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column prop="ip" label="IP" width="130">
          <template #default="{ row }">
            <span class="muted">{{ row.ip || '—' }}</span>
          </template>
        </el-table-column>
        <el-table-column label="详情" width="80">
          <template #default="{ row }">
            <el-button
              v-if="row.detail || row.error_message"
              size="small"
              link
              @click="showDetail(row)"
            >
              查看
            </el-button>
            <span v-else class="muted">—</span>
          </template>
        </el-table-column>

        <template #empty>
          <el-empty description="暂无审计日志" />
        </template>
      </el-table>

      <!-- 分页 -->
      <div class="pagination-wrapper">
        <el-pagination
          v-model:current-page="pagination.page"
          v-model:page-size="pagination.page_size"
          :page-sizes="[20, 50, 100, 200]"
          :total="pagination.total"
          layout="total, sizes, prev, pager, next, jumper"
          @size-change="loadData"
          @current-change="loadData"
        />
      </div>
    </el-card>

    <!-- 详情抽屉 -->
    <el-drawer
      v-model="detailVisible"
      title="审计详情"
      size="500px"
      direction="rtl"
    >
      <div v-if="detailRow" class="detail-content">
        <el-descriptions :column="1" border>
          <el-descriptions-item label="ID">{{ detailRow.id }}</el-descriptions-item>
          <el-descriptions-item label="时间">{{ formatTime(detailRow.created_at) }}</el-descriptions-item>
          <el-descriptions-item label="操作人">{{ detailRow.actor_loginid }}（{{ detailRow.actor_name }}）</el-descriptions-item>
          <el-descriptions-item label="动作">{{ detailRow.action }}</el-descriptions-item>
          <el-descriptions-item label="对象类型">{{ detailRow.target_type || '—' }}</el-descriptions-item>
          <el-descriptions-item label="对象 ID">{{ detailRow.target_id || '—' }}</el-descriptions-item>
          <el-descriptions-item label="对象描述">{{ detailRow.target_label || '—' }}</el-descriptions-item>
          <el-descriptions-item label="结果">{{ detailRow.result }}</el-descriptions-item>
          <el-descriptions-item label="IP">{{ detailRow.ip || '—' }}</el-descriptions-item>
          <el-descriptions-item label="UA">{{ detailRow.user_agent || '—' }}</el-descriptions-item>
        </el-descriptions>
        <h4>业务上下文 (detail)</h4>
        <pre class="detail-json">{{ formatJson(detailRow.detail) }}</pre>
      </div>
    </el-drawer>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onBeforeUnmount } from 'vue'
import { Search, RefreshCw, Download } from 'lucide-vue-next'
import { ElMessage, ElMessageBox } from 'element-plus'
import { formatDate } from '@/utils/timezone'
import api from '@/api'

const items = ref([])
const actions = ref([])
const actors = ref([])
const loading = ref(false)
const exporting = ref(false)
const detailVisible = ref(false)
const detailRow = ref(null)

const filters = reactive({
  keyword: '',
  actor_loginid: '',
  action: '',
  dateRange: [],
  writeOnly: true,  // 默认只看写操作（隐藏 page.view 等页面访问噪音）
})

const pagination = reactive({
  page: 1,
  page_size: 20,
  total: 0,
})

function formatTime(s) {
  if (!s) return '—'
  try {
    return formatDate(s, 'YYYY-MM-DD HH:mm:ss')
  } catch {
    return s
  }
}

function formatJson(v) {
  if (!v) return '（无）'
  try {
    return JSON.stringify(v, null, 2)
  } catch {
    return String(v)
  }
}

function showDetail(row) {
  detailRow.value = row
  detailVisible.value = true
}

async function loadData() {
  loading.value = true
  try {
    const params = {
      page: pagination.page,
      page_size: pagination.page_size,
      include_page_view: !filters.writeOnly,
    }
    if (filters.keyword) params.keyword = filters.keyword
    if (filters.actor_loginid) params.actor_loginid = filters.actor_loginid
    if (filters.action) params.action = filters.action
    if (filters.dateRange && filters.dateRange.length === 2) {
      params.start_time = filters.dateRange[0]
      params.end_time = filters.dateRange[1]
    }
    const res = await api.audit.list(params)
    items.value = res.items || []
    pagination.total = res.total || 0
  } catch (e) {
    console.error('加载审计日志失败', e)
    if (e?.response?.status === 403) {
      ElMessage.error('仅管理员可访问')
    } else {
      ElMessage.error('加载失败：' + (e?.response?.data?.detail || e.message))
    }
  } finally {
    loading.value = false
  }
}

async function loadFilters() {
  try {
    const [a1, a2] = await Promise.all([api.audit.actions(), api.audit.actors()])
    actions.value = a1.items || []
    actors.value = a2.items || []
  } catch (e) {
    console.warn('加载筛选选项失败', e)
  }
}

function handleSearch() {
  pagination.page = 1
  loadData()
}

function handleReset() {
  filters.keyword = ''
  filters.actor_loginid = ''
  filters.action = ''
  filters.dateRange = []
  filters.writeOnly = true
  pagination.page = 1
  loadData()
}

async function handleExport() {
  exporting.value = true
  try {
    const params = {}
    if (filters.keyword) params.keyword = filters.keyword
    if (filters.actor_loginid) params.actor_loginid = filters.actor_loginid
    if (filters.action) params.action = filters.action
    if (filters.dateRange && filters.dateRange.length === 2) {
      params.start_time = filters.dateRange[0]
      params.end_time = filters.dateRange[1]
    }
    params.include_page_view = !filters.writeOnly
    const blob = await api.audit.export(params)
    const a = document.createElement('a')
    a.href = URL.createObjectURL(blob)
    a.download = `audit_logs_${Date.now()}.csv`
    a.click()
    URL.revokeObjectURL(a.href)
    ElMessage.success('导出成功')
  } catch (e) {
    ElMessage.error('导出失败：' + (e?.response?.data?.detail || e.message))
  } finally {
    exporting.value = false
  }
}

onMounted(() => {
  loadData()
  loadFilters()
})
</script>

<style scoped>
.audit-logs-page {
  padding: 0;
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.header-actions {
  display: flex;
  gap: 8px;
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
  margin-bottom: 16px;
}

.audit-table {
  font-size: 13px;
}

.time-text {
  font-family: var(--mc-font-mono);
  font-size: 12px;
}

.actor-text {
  font-weight: 500;
}

.actor-loginid {
  margin-left: 4px;
  color: var(--mc-muted);
  font-size: 11px;
}

.action-code {
  background: color-mix(in srgb, var(--mc-accent) 8%, transparent);
  color: var(--mc-accent);
  padding: 1px 6px;
  border-radius: 3px;
  font-size: 12px;
  font-family: var(--mc-font-mono);
}

.muted {
  color: var(--mc-muted);
  font-size: 12px;
}

.pagination-wrapper {
  margin-top: 20px;
  display: flex;
  justify-content: flex-end;
}

.detail-content h4 {
  margin-top: 20px;
  margin-bottom: 8px;
  font-size: 14px;
  color: var(--mc-ink);
}

.detail-json {
  background: #faf8f4;
  padding: 12px;
  border-radius: 4px;
  font-family: var(--mc-font-mono);
  font-size: 12px;
  overflow-x: auto;
  white-space: pre-wrap;
  word-break: break-all;
}
</style>
