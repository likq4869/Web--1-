<template>
  <div>
    <PageHeader
      title="用户与角色"
      description="账号角色分配、启用停用与密码重置，仅超级管理员可见"
    />

    <div class="hg-users__filters">
      <ElInput
        :model-value="keyword"
        placeholder="按用户名 / 手机号 / ID 搜索"
        clearable
        class="hg-users__search"
        @update:model-value="onKeywordInput"
        @clear="onKeywordClear"
      />
      <ElSelect
        :model-value="role"
        placeholder="角色"
        clearable
        class="hg-users__select"
        @update:model-value="onRoleChange"
      >
        <ElOption label="超级管理员" value="super_admin" />
        <ElOption label="管理员" value="admin" />
        <ElOption label="审批员" value="reviewer" />
        <ElOption label="观察员" value="observer" />
        <ElOption label="团委干事" value="league_officer" />
        <ElOption label="辅导员" value="counselor" />
        <ElOption label="保卫干事" value="security_officer" />
        <ElOption label="审计员" value="auditor" />
        <ElOption label="学生" value="student" />
      </ElSelect>
      <ElSelect
        :model-value="status"
        placeholder="状态"
        clearable
        class="hg-users__select"
        @update:model-value="onStatusChange"
      >
        <ElOption label="启用" value="active" />
        <ElOption label="停用" value="disabled" />
      </ElSelect>
      <div class="hg-users__actions">
        <ElButton :loading="loading" @click="reload">刷新</ElButton>
      </div>
    </div>

    <DataTable
      :rows="rows"
      :loading="loading"
      :error="loadError"
      :total="total"
      :current-page="page"
      :page-size="pageSize"
      :on-retry="reload"
      row-key="user_id"
      empty-title="暂无账号"
      empty-description="当前筛选下没有账号，可调整筛选后重试。"
      @update:current-page="onPageChange"
      @update:page-size="onSizeChange"
    >
      <ElTableColumn prop="user_id" label="用户 ID" min-width="150">
        <template #default="{ row }">
          <span class="tabular">{{ (row as AdminUser).user_id }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn prop="username" label="用户名" min-width="130">
        <template #default="{ row }">
          {{ (row as AdminUser).username ?? '—' }}
        </template>
      </ElTableColumn>
      <ElTableColumn label="角色" width="130">
        <template #default="{ row }">
          <ElTag type="info" size="small">{{ roleLabel((row as AdminUser).role) }}</ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="状态" width="100">
        <template #default="{ row }">
          <ElTag :type="accountStatusBadge((row as AdminUser).status)" size="small">
            {{ accountStatusLabel((row as AdminUser).status) }}
          </ElTag>
        </template>
      </ElTableColumn>
      <ElTableColumn label="最近登录" min-width="150">
        <template #default="{ row }">
          <span class="tabular">{{ formatOpsDateTime((row as AdminUser).last_login_at) }}</span>
        </template>
      </ElTableColumn>
      <ElTableColumn label="操作" width="190" fixed="right">
        <template #default="{ row }">
          <ElButton link type="primary" @click="openEdit(row as AdminUser)">编辑</ElButton>
          <ElButton link type="primary" @click="openReset(row as AdminUser)">重置密码</ElButton>
        </template>
      </ElTableColumn>
    </DataTable>
    <p v-if="actionError" class="hg-users__error" role="alert">{{ actionError }}</p>

    <ElDrawer
      :model-value="editOpen"
      title="编辑账号"
      size="420px"
      destroy-on-close
      @update:model-value="editOpen = $event"
    >
      <div v-if="editing" class="hg-users__form">
        <p class="hg-users__hint">
          正在编辑 <span class="tabular">{{ editing.user_id }}</span>，保存后立即生效并写入审计。
        </p>
        <ElSelect :model-value="editing.role" @update:model-value="onEditRole">
          <ElOption label="超级管理员" value="super_admin" />
          <ElOption label="管理员" value="admin" />
          <ElOption label="审批员" value="reviewer" />
          <ElOption label="观察员" value="observer" />
          <ElOption label="团委干事" value="league_officer" />
          <ElOption label="辅导员" value="counselor" />
          <ElOption label="保卫干事" value="security_officer" />
          <ElOption label="审计员" value="auditor" />
          <ElOption label="学生" value="student" />
        </ElSelect>
        <ElSelect :model-value="editing.status" @update:model-value="onEditStatus">
          <ElOption label="启用" value="active" />
          <ElOption label="停用" value="disabled" />
        </ElSelect>
        <ElButton type="primary" :loading="saving" @click="onSave">保存</ElButton>
      </div>
    </ElDrawer>

    <ElDialog
      :model-value="resetOpen"
      title="重置密码"
      width="420px"
      destroy-on-close
      @update:model-value="resetOpen = $event"
    >
      <div v-if="resetting" class="hg-users__form">
        <p class="hg-users__warn">
          重置后旧密码立即失效，新密码经加密传输后哈希落库，明文不会记入审计。
        </p>
        <ElInput
          :model-value="newPassword"
          type="password"
          show-password
          placeholder="新密码，至少 8 位"
          autocomplete="new-password"
          @update:model-value="newPassword = $event"
        />
        <p v-if="resetError" class="hg-users__error" role="alert">{{ resetError }}</p>
      </div>
      <template #footer>
        <ElButton @click="resetOpen = false">取消</ElButton>
        <ElButton type="primary" :loading="resettingLoading" @click="onConfirmReset">
          确认重置
        </ElButton>
      </template>
    </ElDialog>
  </div>
</template>

<script setup lang="ts">
import { onMounted, ref } from 'vue'
import {
  ElButton,
  ElDialog,
  ElDrawer,
  ElInput,
  ElMessage,
  ElMessageBox,
  ElOption,
  ElSelect,
  ElTableColumn,
  ElTag,
} from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import DataTable from '@/components/DataTable.vue'
import { listUsers, resetUserPassword, updateAdminUser, type AdminUser } from '@/api/ops'
import { ApiError } from '@/api/types'
import {
  accountStatusBadge,
  accountStatusLabel,
  formatOpsDateTime,
  roleLabel,
} from '@/views/models/opsFormat'

/** 可编辑的账号草稿（抽离响应式细节，提交时再收敛为请求体） */
interface UserDraft {
  user_id: string
  role: string
  status: 'active' | 'disabled'
}

const rows = ref<AdminUser[]>([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)
const loading = ref(false)
const loadError = ref<string | null>(null)
const actionError = ref<string | null>(null)

const keyword = ref('')
const role = ref('')
const status = ref('')

const editOpen = ref(false)
const editing = ref<UserDraft | null>(null)
const saving = ref(false)

const resetOpen = ref(false)
const resetting = ref<AdminUser | null>(null)
const newPassword = ref('')
const resetError = ref<string | null>(null)
const resettingLoading = ref(false)

let fetchSeq = 0
let keywordTimer: ReturnType<typeof setTimeout> | null = null

async function fetchData(): Promise<void> {
  const seq = (fetchSeq += 1)
  loading.value = true
  loadError.value = null
  try {
    const result = await listUsers({
      page: page.value,
      page_size: pageSize.value,
      keyword: keyword.value.trim() === '' ? undefined : keyword.value.trim(),
      role: role.value === '' ? undefined : role.value,
      status: status.value === '' ? undefined : status.value,
    })
    if (seq !== fetchSeq) return
    rows.value = result.items
    total.value = result.total
  } catch (error) {
    if (seq !== fetchSeq) return
    rows.value = []
    loadError.value = error instanceof ApiError ? error.message : '用户列表加载失败'
  } finally {
    if (seq === fetchSeq) loading.value = false
  }
}

function reload(): void {
  void fetchData()
}

function onKeywordInput(value: string): void {
  keyword.value = value
  if (keywordTimer !== null) clearTimeout(keywordTimer)
  keywordTimer = setTimeout(() => {
    page.value = 1
    void fetchData()
  }, 300)
}

function onKeywordClear(): void {
  keyword.value = ''
  page.value = 1
  void fetchData()
}

function onRoleChange(value: string): void {
  role.value = value ?? ''
  page.value = 1
  void fetchData()
}

function onStatusChange(value: string): void {
  status.value = value ?? ''
  page.value = 1
  void fetchData()
}

function onPageChange(next: number): void {
  page.value = next
  void fetchData()
}

function onSizeChange(size: number): void {
  pageSize.value = size
  page.value = 1
  void fetchData()
}

function openEdit(row: AdminUser): void {
  actionError.value = null
  editing.value = {
    user_id: row.user_id,
    role: row.role,
    status: row.status === 'disabled' ? 'disabled' : 'active',
  }
  editOpen.value = true
}

function onEditRole(value: string): void {
  if (editing.value) editing.value.role = value
}

function onEditStatus(value: 'active' | 'disabled'): void {
  if (editing.value) editing.value.status = value
}

async function onSave(): Promise<void> {
  if (!editing.value) return
  saving.value = true
  actionError.value = null
  try {
    await updateAdminUser(editing.value.user_id, {
      role: editing.value.role,
      status: editing.value.status,
    })
    ElMessage.success('账号已更新')
    editOpen.value = false
    editing.value = null
    await fetchData()
  } catch (error) {
    actionError.value = error instanceof ApiError ? error.message : '保存失败，请重试'
  } finally {
    saving.value = false
  }
}

function openReset(row: AdminUser): void {
  resetting.value = row
  newPassword.value = ''
  resetError.value = null
  resetOpen.value = true
}

async function onConfirmReset(): Promise<void> {
  if (!resetting.value) return
  if (newPassword.value.length < 8) {
    resetError.value = '新密码至少 8 位'
    return
  }
  const target = resetting.value
  try {
    await ElMessageBox.confirm(
      `确认为 ${target.user_id} 重置密码？旧密码将立即失效，该操作会写入审计。`,
      '重置密码',
      { confirmButtonText: '确认重置', cancelButtonText: '取消', type: 'warning' },
    )
  } catch {
    return
  }
  resettingLoading.value = true
  resetError.value = null
  try {
    await resetUserPassword(target.user_id, newPassword.value)
    ElMessage.success('密码已重置')
    resetOpen.value = false
    resetting.value = null
    newPassword.value = ''
  } catch (error) {
    resetError.value = error instanceof ApiError ? error.message : '重置失败，请重试'
  } finally {
    resettingLoading.value = false
  }
}

onMounted(() => {
  void fetchData()
})
</script>

<style scoped lang="scss" src="./_styles/users.scss"></style>
