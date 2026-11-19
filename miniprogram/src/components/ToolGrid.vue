<template>
  <view class="tool-grid">
    <view
      v-for="(item, i) in items"
      :key="item.id"
      class="tool pressable anim-rise"
      :class="'anim-delay-' + (i % 4)"
      @click="onSelect(item.id)"
    >
      <view class="tool-icon" :class="'tone-' + item.tone">
        <UniIcons :type="iconType(item.icon)" :color="iconColor(item.tone)" size="20" />
      </view>
      <text class="tool-label">{{ item.label }}</text>
    </view>
  </view>
</template>

<script setup lang="ts">
import UniIcons from '@dcloudio/uni-ui/lib/uni-icons/uni-icons.vue';

export interface ToolItem {
  id: string;
  label: string;
  icon: 'scan' | 'bike' | 'rank' | 'mall';
  tone: 'primary' | 'success' | 'warning' | 'neutral';
}

const props = withDefaults(defineProps<{ items?: ToolItem[] }>(), {
  items: () => [],
});
const emit = defineEmits<{ (e: 'select', id: string): void }>();

/** 官方 uni-icons 字体图标映射（本地 ttf，不走远端/SVG）：扫码/绑定/排行/商城 */
function iconType(icon: ToolItem['icon']): string {
  if (icon === 'scan') return 'scan';
  if (icon === 'bike') return 'locked';
  if (icon === 'rank') return 'medal';
  return 'shop';
}

/** 图标色随 tone 走语义色（只小面积使用，design.md §11） */
function iconColor(tone: ToolItem['tone']): string {
  if (tone === 'primary') return '#2f6b4f';
  if (tone === 'success') return '#1f9d46';
  if (tone === 'warning') return '#b7791f';
  return '#2f6b4f';
}

function onSelect(id: string): void {
  emit('select', id);
}

void props;
</script>

<style lang="scss" scoped src="./ToolGrid.scss"></style>
