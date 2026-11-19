<template>
  <view class="notice" :class="'is-' + level">
    <text class="notice-title num">{{ title }}</text>
    <text v-if="subtitle" class="notice-sub">{{ subtitle }}</text>
    <view v-if="primaryText || secondaryText" class="notice-actions">
      <text v-if="secondaryText" class="link pressable" @click="onSecondary">{{ secondaryText }}</text>
      <text v-if="primaryText" class="link is-strong pressable" @click="onPrimary">{{ primaryText }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
const props = withDefaults(
  defineProps<{
    level?: 'warning' | 'danger' | 'info';
    title?: string;
    subtitle?: string;
    primaryText?: string;
    secondaryText?: string;
  }>(),
  { level: 'warning', title: '', subtitle: '', primaryText: '', secondaryText: '' },
);
const emit = defineEmits<{ (e: 'primary'): void; (e: 'secondary'): void }>();

function onPrimary(): void {
  emit('primary');
}

function onSecondary(): void {
  emit('secondary');
}

void props;
</script>

<style lang="scss" scoped src="./NoticeBanner.scss"></style>
