<template>
  <div class="hg-table-wrap">
    <!-- 加载态：骨架屏而非旋转菊花 -->
    <div v-if="loading" class="hg-table__skeleton" aria-busy="true" aria-label="加载中">
      <div v-for="rowIdx in skeletonRows" :key="rowIdx" class="hg-table__skeleton-row">
        <span class="hg-table__skeleton-bar hg-table__skeleton-bar--head" />
        <span
          v-for="col in columnCount"
          :key="col"
          class="hg-table__skeleton-bar"
          :style="{ width: `${40 + ((col * 13) % 40)}%` }"
        />
      </div>
    </div>

    <!-- 错误态 -->
    <div v-else-if="error" class="hg-table__error" role="alert">
      <p class="hg-table__error-text">{{ errorMessage }}</p>
      <ElButton v-if="onRetry" size="small" @click="onRetry">重试</ElButton>
    </div>

    <!-- 空态 -->
    <EmptyState v-else-if="rows.length === 0" :title="emptyTitle" :description="emptyDescription">
      <template v-if="$slots.empty" #action>
        <slot name="empty" />
      </template>
    </EmptyState>

    <!-- 数据态 -->
    <ElTable
      v-else
      v-loading="false"
      :data="rows"
      :row-key="rowKey"
      class="hg-table"
      :stripe="false"
      @row-click="onRowClick"
      @selection-change="onSelectionChange"
    >
      <slot />
    </ElTable>

    <!-- 分页 -->
    <div v-if="showPagination" class="hg-table__pagination">
      <span class="hg-table__total tabular">
        共 {{ total }} 条 · 第 {{ currentPage }} / {{ totalPages }} 页
      </span>
      <ElPagination
        layout="prev, pager, next"
        :current-page="currentPage"
        :page-size="pageSize"
        :total="total"
        :pager-count="5"
        size="small"
        background
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </div>
  </div>
</template>

<script setup lang="ts" generic="T extends Record<string, unknown>">
import { computed } from 'vue'
import { ElButton, ElPagination, ElTable } from 'element-plus'
import EmptyState from './EmptyState.vue'

const props = withDefaults(
  defineProps<{
    /** 数据行 */
    rows: T[]
    /** 加载中 */
    loading?: boolean
    /** 错误信息 */
    error?: string | null
    /** 重试回调 */
    onRetry?: (() => void) | null
    /** 行唯一键字段名 */
    rowKey?: string
    /** 总条数 */
    total?: number
    /** 当前页码（1 起） */
    currentPage?: number
    /** 每页条数 */
    pageSize?: number
    /** 是否显示分页 */
    showPagination?: boolean
    /** 空态标题 */
    emptyTitle?: string
    /** 空态描述 */
    emptyDescription?: string
    /** 骨架屏行数 */
    skeletonRows?: number
    /** 行点击回调 */
    onRowClick?: ((row: T) => void) | null
  }>(),
  {
    loading: false,
    error: null,
    onRetry: null,
    rowKey: 'id',
    total: 0,
    currentPage: 1,
    pageSize: 20,
    showPagination: true,
    emptyTitle: '暂无数据',
    emptyDescription: undefined,
    skeletonRows: 6,
    onRowClick: null,
  },
)

const emit = defineEmits<{
  'update:currentPage': [page: number]
  'update:pageSize': [size: number]
  'selection-change': [rows: T[]]
}>()

const totalPages = computed(() =>
  props.pageSize > 0 ? Math.max(1, Math.ceil(props.total / props.pageSize)) : 1,
)

const columnCount = computed(() => Math.max(3, Math.min(6, props.rows.length || 4)))

const errorMessage = computed(() => props.error ?? '数据加载失败')

function onPageChange(page: number): void {
  emit('update:currentPage', page)
}

function onSizeChange(size: number): void {
  emit('update:pageSize', size)
}

function onSelectionChange(selection: T[]): void {
  emit('selection-change', selection)
}
</script>

<style scoped lang="scss" src="./_styles/data-table.scss"></style>
