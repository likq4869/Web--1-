<template>
  <view class="empty">
    <view class="empty-icon" aria-hidden="true">
      <UniIcons type="info" color="#b9c4bc" size="24" />
    </view>
    <text class="empty-title">{{ title }}</text>
    <text v-if="description" class="empty-desc">{{ description }}</text>
    <button v-if="actionText" class="quiet-btn pressable" @click="onAction">{{ actionText }}</button>
  </view>
</template>

<script setup lang="ts">
import UniIcons from '@dcloudio/uni-ui/lib/uni-icons/uni-icons.vue';
const props = withDefaults(
  defineProps<{ title?: string; description?: string; actionText?: string }>(),
  { title: '还没有内容', description: '', actionText: '' },
);
const emit = defineEmits<{ (e: 'action'): void }>();

function onAction(): void {
  emit('action');
}

void props;
</script>

<style lang="scss" scoped src="./EmptyState.scss"></style>
