<template>
  <!--
    全局错误边界：捕获子组件渲染异常，避免整页白屏。
    通过作用域插槽暴露 `reset` —— 父组件用 `v-slot="{ reset }"` 取得重载入口。
    （此前默认插槽未提供该 prop，父组件渲染时访问 `reset` 会抛 TypeError，
      被本错误边界自身捕获，导致整页永久白屏。）
  -->
  <slot v-if="!error" :reset="reset" :reload-key="reloadKey" />

  <!-- 异常态：显示兜底提示与恢复入口 -->
  <div v-else class="hg-error-boundary" role="alert">
    <p class="hg-error-boundary__title">页面出现异常</p>
    <p class="hg-error-boundary__desc">
      界面渲染时发生错误。可以尝试重新加载当前视图；若持续出现，请联系管理员并提供 trace 信息。
    </p>
    <pre v-if="traceId" class="hg-error-boundary__trace mono">{{ traceId }}</pre>
    <div class="hg-error-boundary__actions">
      <button class="hg-error-boundary__button" type="button" @click="reset">重新加载</button>
      <button class="hg-error-boundary__button is-primary" type="button" @click="goHome">
        返回首页
      </button>
    </div>
  </div>
</template>

<script setup lang="ts">
import { onErrorCaptured, ref } from 'vue'
import { useRouter } from 'vue-router'

const router = useRouter()
const error = ref<Error | null>(null)
const traceId = ref('')
/** 重载计数：递增即迫使插槽内容重建 */
const reloadKey = ref(0)

/**
 * 捕获子组件渲染/生命周期异常。
 * 记录 trace 信息便于后端与前端联合排查。
 */
onErrorCaptured((err: unknown) => {
  error.value = err instanceof Error ? err : new Error(String(err))
  traceId.value = `UI-${Date.now().toString(36).toUpperCase()}`
  // 返回 false 阻止错误继续向上冒泡到 Vue 根
  return false
})

/**
 * 清除错误并重建插槽内容。
 *
 * 仅清空错误状态不足以恢复已损坏的组件树 —— 同时递增 reloadKey，
 * 让父组件用其作为 key 重建 RouterView。
 */
function reset(): void {
  error.value = null
  reloadKey.value += 1
}

function goHome(): void {
  error.value = null
  reloadKey.value += 1
  void router.replace('/')
}
</script>

<style scoped lang="scss">
.hg-error-boundary {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  min-height: 60vh;
  padding: var(--space-6);
  text-align: center;
}

.hg-error-boundary__title {
  font-size: var(--text-title-size);
  font-weight: var(--text-title-weight);
  color: var(--color-text);
}

.hg-error-boundary__desc {
  max-width: 460px;
  font-size: var(--text-body-size);
  line-height: var(--text-body-line);
  color: var(--color-text-2);
}

.hg-error-boundary__trace {
  padding: var(--space-2) var(--space-3);
  font-size: var(--text-caption-size);
  color: var(--color-text-3);
  background-color: var(--color-surface-2);
  border-radius: var(--radius-md);
}

.hg-error-boundary__actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-2);
}

.hg-error-boundary__button {
  height: var(--control-height-touch);
  padding: 0 var(--space-5);
  font-size: var(--text-body-size);
  font-weight: var(--text-subhead-weight);
  color: var(--color-primary);
  background-color: var(--color-surface-2);
  border-radius: var(--radius-lg);
  transition: background-color var(--duration-fast) var(--ease-standard);

  &:hover {
    background-color: var(--color-sep-strong);
  }

  &.is-primary {
    color: var(--color-surface);
    background-color: var(--color-primary);

    &:hover {
      background-color: var(--color-primary-hover);
    }
  }
}
</style>
