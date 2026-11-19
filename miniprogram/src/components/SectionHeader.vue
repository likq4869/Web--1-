<template>
  <view class="section-head">
    <text class="section-title">{{ title }}</text>
    <text v-if="actionText" class="section-action pressable" @click="onAction">{{ actionText }}</text>
  </view>
</template>

<script setup lang="ts">
const props = withDefaults(defineProps<{ title?: string; actionText?: string }>(), {
  title: '',
  actionText: '',
});
const emit = defineEmits<{ (e: 'action'): void }>();

function onAction(): void {
  emit('action');
}

void props;
</script>

<style lang="scss" scoped src="./SectionHeader.scss"></style>
