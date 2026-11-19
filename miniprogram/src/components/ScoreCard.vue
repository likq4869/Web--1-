<template>
  <view class="score">
    <text class="label">文明积分</text>
    <AnimatedNumber :value="balance" class="score-num num" />
    <text class="score-sub">{{ sub }}</text>
    <view class="progress" aria-hidden="true">
      <view class="progress-fill" :style="'width:' + pct + '%;'" />
    </view>
    <text v-if="streakText" class="streak">{{ streakText }}</text>
    <view v-if="cells && cells.length" class="score-grid">
      <view v-for="c in cells" :key="c.label" class="score-cell">
        <text class="cell-label">{{ c.label }}</text>
        <text class="cell-value num">{{ c.value }}</text>
      </view>
    </view>
  </view>
</template>

<script setup lang="ts">
import AnimatedNumber from './AnimatedNumber.vue';

export interface ScoreCell {
  label: string;
  value: string;
}

const props = withDefaults(
  defineProps<{
    balance?: number;
    sub?: string;
    pct?: number;
    streakText?: string;
    cells?: ScoreCell[];
  }>(),
  { balance: 0, sub: '', pct: 0, streakText: '', cells: () => [] },
);

void props;
</script>

<style lang="scss" scoped src="./ScoreCard.scss"></style>
