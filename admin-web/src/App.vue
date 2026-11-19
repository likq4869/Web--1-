<template>
  <!--
    全局错误边界：捕获子组件渲染异常，避免整页白屏。
    通过作用域插槽取得 reloadKey —— ErrorBoundary 内部提供该 prop，
    用作 RouterView 的 key：错误恢复后视图被重建，组件树真正刷新。
    （此前默认插槽未提供 reset，父组件渲染时访问 `reset` 会抛 TypeError，
      被本错误边界自身捕获，导致整页永久白屏。）
  -->
  <ErrorBoundary v-slot="{ reloadKey }">
    <RouterView :key="reloadKey" />
  </ErrorBoundary>
</template>

<script setup lang="ts">
import ErrorBoundary from '@/components/ErrorBoundary.vue'
</script>
