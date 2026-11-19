<template>
  <div class="hg-error">
    <p class="hg-error__code tabular">404</p>
    <h1 class="hg-error__title">页面不存在</h1>
    <p class="hg-error__desc">
      你访问的地址可能已被移动或删除。请检查链接是否正确，或返回首页继续。
    </p>
    <ElButton type="primary" class="hg-error__action" @click="goHome">返回首页</ElButton>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ElButton } from 'element-plus'

const router = useRouter()

function goHome(): void {
  void router.replace('/')
}
</script>

<style scoped lang="scss">
@use '@/styles/mixins.scss' as *;

.hg-error {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: var(--space-3);
  min-height: 100vh;
  padding: var(--space-6);
  text-align: center;
  background-color: var(--color-bg);
}

.hg-error__code {
  font-size: 64px;
  line-height: 1;
  font-weight: var(--text-large-title-weight);
  letter-spacing: -2px;
  color: var(--color-text-4);
}

.hg-error__title {
  margin: 0;
  font-size: var(--text-title-size);
  font-weight: var(--text-title-weight);
  color: var(--color-text);
}

.hg-error__desc {
  max-width: 420px;
  font-size: var(--text-body-size);
  line-height: var(--text-body-line);
  color: var(--color-text-2);
}

.hg-error__action {
  margin-top: var(--space-2);
  height: var(--control-height-touch);
  padding: 0 var(--space-5);
  font-size: var(--text-body-size);
  border-radius: var(--radius-lg);
}
</style>
