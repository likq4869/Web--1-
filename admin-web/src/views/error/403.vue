<template>
  <div class="hg-error">
    <p class="hg-error__code tabular">403</p>
    <h1 class="hg-error__title">无访问权限</h1>
    <p class="hg-error__desc">
      当前账号的角色没有访问该页面的权限。如需访问，请联系系统管理员调整账号权限。
    </p>
    <div class="hg-error__actions">
      <ElButton @click="goBack">返回上一页</ElButton>
      <ElButton type="primary" @click="goHome">返回首页</ElButton>
    </div>
  </div>
</template>

<script setup lang="ts">
import { useRouter } from 'vue-router'
import { ElButton } from 'element-plus'

const router = useRouter()

function goBack(): void {
  if (window.history.length > 1) {
    router.back()
  } else {
    void router.replace('/')
  }
}

function goHome(): void {
  void router.replace('/')
}
</script>

<style scoped lang="scss">
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

.hg-error__actions {
  display: flex;
  gap: var(--space-2);
  margin-top: var(--space-2);
}
</style>
