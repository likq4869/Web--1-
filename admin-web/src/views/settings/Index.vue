<template>
  <div>
    <PageHeader title="系统设置" description="点位管理、模型配置与审计日志" />

    <div class="hg-settings">
      <section class="hg-settings__section">
        <h2 class="hg-settings__title">外观</h2>
        <div class="hg-settings__row">
          <span class="hg-settings__label">主题模式</span>
          <ElRadioGroup
            :model-value="appStore.theme"
            size="small"
            @update:model-value="onThemeChange"
          >
            <ElRadioButton value="light">浅色</ElRadioButton>
            <ElRadioButton value="dark">深色</ElRadioButton>
            <ElRadioButton value="system">跟随系统</ElRadioButton>
          </ElRadioGroup>
        </div>
      </section>
    </div>
  </div>
</template>

<script setup lang="ts">
import { ElRadioButton, ElRadioGroup } from 'element-plus'
import PageHeader from '@/components/PageHeader.vue'
import { useAppStore, type ThemeMode } from '@/stores/app'

const appStore = useAppStore()

function onThemeChange(value: ThemeMode): void {
  appStore.setTheme(value)
}
</script>

<style scoped lang="scss">
.hg-settings {
  display: flex;
  flex-direction: column;
  gap: var(--card-gap);
}

.hg-settings__section {
  padding: var(--card-padding);
  background-color: var(--color-surface);
  border-radius: var(--radius-xl);
  box-shadow: var(--shadow-card);
}

.hg-settings__title {
  margin: 0 0 var(--space-4);
  font-size: var(--text-headline-size);
  font-weight: var(--text-headline-weight);
  color: var(--color-text);
}

.hg-settings__row {
  display: flex;
  align-items: center;
  gap: var(--space-4);
}

.hg-settings__label {
  font-size: var(--text-body-size);
  color: var(--color-text-2);
}
</style>
