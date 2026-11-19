<template>
  <ElDialog
    :model-value="visible"
    title="选择学生"
    width="560px"
    destroy-on-close
    @update:model-value="onVisibleChange"
    @closed="onClosed"
  >
    <div class="hg-picker">
      <ElInput
        :model-value="keyword"
        placeholder="输入学号 / 姓名 / 手机号搜索"
        clearable
        @update:model-value="onKeywordInput"
        @clear="onClear"
      >
        <template #prefix>
          <ElIcon><Search /></ElIcon>
        </template>
      </ElInput>

      <div v-if="loading" class="hg-picker__loading" aria-busy="true" aria-label="搜索中">
        <ElSkeleton :rows="3" animated />
      </div>

      <p v-else-if="error" class="hg-picker__error" role="alert">
        {{ error }}
        <ElButton size="small" @click="search">重试</ElButton>
      </p>

      <EmptyState
        v-else-if="students.length === 0"
        title="未找到学生"
        description="换个关键词试试，例如学号前几位或姓名。"
      />

      <ul v-else class="hg-picker__list" role="listbox" aria-label="学生候选">
        <li
          v-for="student in students"
          :key="student.student_id"
          class="hg-picker__item"
          :class="{ 'is-selected': student.student_id === selectedId }"
        >
          <button type="button" class="hg-picker__option" @click="pick(student)">
            <span class="hg-picker__name">{{ student.name }}</span>
            <span class="hg-picker__meta tabular">
              {{ student.student_id }} · {{ student.class_name ?? '未分班' }}
            </span>
          </button>
        </li>
      </ul>
    </div>

    <template #footer>
      <ElButton @click="close">取消</ElButton>
      <ElButton type="primary" :disabled="selected === null" @click="confirm">确定</ElButton>
    </template>
  </ElDialog>
</template>

<script setup lang="ts">
import { ref, watch } from 'vue'
import { ElButton, ElDialog, ElIcon, ElInput, ElSkeleton } from 'element-plus'
import { Search } from '@element-plus/icons-vue'
import EmptyState from './EmptyState.vue'
import { listStudents, type Student } from '@/api/students'
import { ApiError } from '@/api/types'

const props = withDefaults(
  defineProps<{
    /** 弹窗可见性（v-model:visible） */
    visible?: boolean
    /** 已选中的学号（高亮用） */
    modelValue?: string | null
  }>(),
  {
    visible: false,
    modelValue: null,
  },
)

const emit = defineEmits<{
  'update:visible': [visible: boolean]
  'update:modelValue': [studentId: string | null]
  select: [student: Student]
}>()

const keyword = ref('')
const students = ref<Student[]>([])
const selected = ref<Student | null>(null)
const selectedId = ref<string | null>(props.modelValue)
const loading = ref(false)
const error = ref<string | null>(null)

/** 远程搜索防抖 + 取消旧请求：序号递增，过期响应直接丢弃 */
let debounceTimer: ReturnType<typeof setTimeout> | null = null
let requestSeq = 0

watch(
  () => props.visible,
  (visible) => {
    if (visible) {
      keyword.value = ''
      students.value = []
      selected.value = null
      selectedId.value = props.modelValue
      error.value = null
      void search()
    }
  },
)

watch(
  () => props.modelValue,
  (value) => {
    selectedId.value = value
  },
)

function onVisibleChange(visible: boolean): void {
  emit('update:visible', visible)
}

function onKeywordInput(value: string): void {
  keyword.value = value
  if (debounceTimer !== null) clearTimeout(debounceTimer)
  debounceTimer = setTimeout(() => {
    void search()
  }, 300)
}

function onClear(): void {
  keyword.value = ''
  void search()
}

async function search(): Promise<void> {
  const seq = (requestSeq += 1)
  loading.value = true
  error.value = null
  try {
    const page = await listStudents({
      page: 1,
      page_size: 10,
      keyword: keyword.value.trim() === '' ? undefined : keyword.value.trim(),
      sort: 'student_id',
      order: 'asc',
    })
    // 旧请求的结果直接丢弃，避免竞态覆盖新结果
    if (seq !== requestSeq) return
    students.value = page.items
  } catch (err) {
    if (seq !== requestSeq) return
    students.value = []
    error.value = err instanceof ApiError ? err.message : '搜索失败，请重试'
  } finally {
    if (seq === requestSeq) loading.value = false
  }
}

function pick(student: Student): void {
  selected.value = student
  selectedId.value = student.student_id
}

function confirm(): void {
  if (selected.value === null) return
  emit('update:modelValue', selected.value.student_id)
  emit('select', selected.value)
  close()
}

function close(): void {
  emit('update:visible', false)
}

function onClosed(): void {
  if (debounceTimer !== null) {
    clearTimeout(debounceTimer)
    debounceTimer = null
  }
  // 旧请求失效：序号递增使飞行中的响应被丢弃
  requestSeq += 1
  loading.value = false
}
</script>

<style scoped lang="scss">
.hg-picker {
  display: flex;
  flex-direction: column;
  gap: var(--space-3);
  min-height: 280px;
}

.hg-picker__loading {
  padding: var(--space-2) 0;
}

.hg-picker__error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: var(--space-3);
  padding: var(--space-3) var(--space-4);
  font-size: var(--text-footnote-size);
  color: var(--color-danger);
  background-color: var(--color-danger-tint);
  border-radius: var(--radius-md);
}

.hg-picker__list {
  display: flex;
  flex-direction: column;
  gap: var(--space-1);
  max-height: 320px;
  overflow: auto;
}

.hg-picker__item {
  border-radius: var(--radius-md);

  &.is-selected {
    background-color: var(--color-primary-tint);
  }
}

.hg-picker__option {
  display: flex;
  flex-direction: column;
  align-items: flex-start;
  gap: var(--space-1);
  width: 100%;
  padding: var(--space-2) var(--space-3);
  text-align: left;
  border-radius: var(--radius-md);

  &:hover {
    background-color: var(--color-surface-2);
  }

  .is-selected &:hover {
    background-color: transparent;
  }
}

.hg-picker__name {
  font-size: var(--text-body-size);
  font-weight: var(--text-subhead-weight);
  color: var(--color-text);
}

.hg-picker__meta {
  font-size: var(--text-footnote-size);
  color: var(--color-text-3);
}
</style>
