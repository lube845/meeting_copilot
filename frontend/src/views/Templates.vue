<template>
  <div class="templates-page">
    <el-card>
      <template #header>
        <div class="card-header">
          <span class="card-title">会议纪要模板</span>
          <el-button type="primary" @click="openCreateDialog">
            <el-icon><Plus /></el-icon>
            新建模板
          </el-button>
        </div>
      </template>

      <el-alert
        v-if="templates && Object.keys(templates).length === 0"
        type="info"
        :closable="false"
        title="还没有任何模板"
        description="点击右上角'新建模板'开始创建你的第一个会议纪要模板。"
        show-icon
      />

      <el-table
        v-else
        :data="templateList"
        stripe
        v-loading="loading"
        :empty-text="'暂无模板'"
      >
        <el-table-column prop="key" label="模板名称" min-width="160" show-overflow-tooltip>
          <template #default="{ row }">
            <el-tag size="small" type="info">{{ row.key }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="预览" min-width="320">
          <template #default="{ row }">
            <div class="preview">{{ row.preview }}</div>
          </template>
        </el-table-column>
        <el-table-column label="长度" width="100" align="center">
          <template #default="{ row }">
            {{ row.length }}
          </template>
        </el-table-column>
        <el-table-column label="占位符" min-width="220">
          <template #default="{ row }">
            <el-tag
              v-for="ph in row.placeholders"
              :key="ph"
              size="small"
              type="warning"
              effect="plain"
              class="ph-tag"
            >
              {{ ph }}
            </el-tag>
            <span v-if="!row.placeholders.length" class="muted">—</span>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" align="center" fixed="right">
          <template #default="{ row }">
            <el-button size="small" link type="primary" @click="openEditDialog(row)">编辑</el-button>
            <el-popconfirm
              :title="`确定删除模板 “${row.key}” ？`"
              @confirm="handleDelete(row)"
            >
              <template #reference>
                <el-button size="small" link type="danger">删除</el-button>
              </template>
            </el-popconfirm>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 编辑/新建对话框 -->
    <el-dialog
      v-model="dialog.visible"
      :title="dialog.mode === 'create' ? '新建模板' : '编辑模板'"
      width="720px"
      :close-on-click-modal="false"
      @close="resetDialog"
      destroy-on-close
    >
      <el-form :model="dialog.form" :rules="dialog.rules" ref="formRef" label-width="92px">
        <el-form-item label="模板名称" prop="key">
          <el-input
            v-model="dialog.form.key"
            placeholder="例如：周会纪要"
            :disabled="dialog.mode === 'edit'"
          />
          <div v-if="dialog.mode === 'edit'" class="form-tip">
            模板名称作为唯一标识，不可修改
          </div>
        </el-form-item>
        <el-form-item label="模板内容" prop="content">
          <el-input
            ref="contentTextareaRef"
            v-model="dialog.form.content"
            type="textarea"
            :rows="16"
            placeholder="支持 Markdown 语法；下方占位符按钮可一键插入到光标位置"
            class="template-textarea"
            resize="vertical"
          />
        </el-form-item>
        <el-form-item>
          <el-space wrap>
            <el-button size="small" @click="insertPlaceholder('{{会议时间}}')">+ 会议时间</el-button>
            <el-button size="small" @click="insertPlaceholder('{{会议主题}}')">+ 会议主题</el-button>
            <el-button size="small" @click="insertPlaceholder('{{会议议题}}')">+ 会议议题</el-button>
            <el-button size="small" @click="insertPlaceholder('{{会议地址}}')">+ 会议地址</el-button>
            <el-button size="small" @click="insertPlaceholder('{{参会人员}}')">+ 参会人员</el-button>
          </el-space>
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="dialog.visible = false">取消</el-button>
        <el-button type="primary" :loading="dialog.saving" @click="handleSubmit">
          保存
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, nextTick } from 'vue'
import { Plus } from 'lucide-vue-next'
import { ElMessage } from 'element-plus'
import api from '@/api'

const loading = ref(false)
const templates = ref({})  // 服务端原始 dict

const templateList = computed(() => {
  return Object.entries(templates.value).map(([key, content]) => {
    // 提取占位符 {{xxx}}
    const placeholders = (content.match(/\{\{[^}]+\}\}/g) || [])
    return {
      key,
      content,
      preview: content.replace(/\n+/g, ' ').slice(0, 100) + (content.length > 100 ? '…' : ''),
      length: content.length,
      placeholders: [...new Set(placeholders)],
    }
  })
})

const dialog = reactive({
  visible: false,
  mode: 'create',  // 'create' | 'edit'
  saving: false,
  form: { key: '', content: '' },
  rules: {
    key: [{ required: true, message: '请输入模板名称', trigger: 'blur' }],
    content: [{ required: true, message: '请输入模板内容', trigger: 'blur' }],
  },
})

const formRef = ref(null)
const contentTextareaRef = ref(null)

async function loadData() {
  loading.value = true
  try {
    const res = await api.templates.list()
    templates.value = res.templates || {}
  } catch (e) {
    ElMessage.error('加载模板失败')
  } finally {
    loading.value = false
  }
}

function openCreateDialog() {
  dialog.mode = 'create'
  dialog.form = { key: '', content: '' }
  dialog.visible = true
  nextTick(() => formRef.value?.clearValidate?.())
}

function openEditDialog(row) {
  dialog.mode = 'edit'
  dialog.form = { key: row.key, content: row.content }
  dialog.visible = true
  nextTick(() => formRef.value?.clearValidate?.())
}

function resetDialog() {
  dialog.form = { key: '', content: '' }
  dialog.saving = false
}

async function handleSubmit() {
  const valid = await formRef.value.validate().catch(() => false)
  if (!valid) return
  dialog.saving = true
  try {
    await api.templates.upsert(dialog.form.key.trim(), dialog.form.content)
    ElMessage.success(dialog.mode === 'create' ? '模板已创建' : '模板已更新')
    dialog.visible = false
    await loadData()
  } catch (e) {
    ElMessage.error('保存失败：' + (e?.response?.data?.detail || e.message))
  } finally {
    dialog.saving = false
  }
}

async function handleDelete(row) {
  try {
    await api.templates.delete(row.key)
    ElMessage.success(`模板 “${row.key}” 已删除`)
    await loadData()
  } catch (e) {
    ElMessage.error('删除失败：' + (e?.response?.data?.detail || e.message))
  }
}

// 在 textarea 当前光标位置插入占位符
function insertPlaceholder(ph) {
  const el = contentTextareaRef.value?.textarea
  if (!el) {
    // 没有 textarea 元素（理论上不会发生），退化为追加
    dialog.form.content = (dialog.form.content || '') + ph
    return
  }

  const start = el.selectionStart ?? (dialog.form.content || '').length
  const end = el.selectionEnd ?? start
  const before = (dialog.form.content || '').slice(0, start)
  const after = (dialog.form.content || '').slice(end)

  dialog.form.content = before + ph + after

  // 等 DOM 更新后，把光标移到插入文本之后
  nextTick(() => {
    const newPos = start + ph.length
    el.focus()
    el.setSelectionRange(newPos, newPos)
  })
}

onMounted(() => {
  loadData()
})
</script>

<style scoped>
.templates-page {
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

.preview {
  font-size: 13px;
  color: var(--mc-muted);
  font-family: 'SF Mono', 'Consolas', monospace;
  line-height: 1.5;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 100%;
}

.ph-tag {
  margin-right: 6px;
  margin-bottom: 4px;
  font-family: 'SF Mono', 'Consolas', monospace;
}

.muted {
  color: var(--mc-muted);
}

.form-tip {
  font-size: 12px;
  color: var(--mc-muted);
  margin-top: 4px;
}

.template-textarea :deep(textarea) {
  font-family: 'SF Mono', 'Consolas', 'Monaco', monospace;
  font-size: 13px;
  line-height: 1.6;
}
</style>