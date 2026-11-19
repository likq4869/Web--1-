<template>
  <ElDrawer
    :model-value="open"
    title="学生详情"
    size="600px"
    destroy-on-close
    @update:model-value="emit('update:open', $event)"
  >
    <div v-if="detailLoading" aria-busy="true" aria-label="加载中">
      <ElSkeleton :rows="5" animated />
    </div>
    <p v-else-if="detailError" class="hg-student-detail__error" role="alert">
      {{ detailError }}
      <ElButton size="small" @click="emit('retry')">重试</ElButton>
    </p>
    <div v-else-if="detail" class="hg-student-detail">
      <section class="hg-student-detail__section">
        <h3 class="hg-student-detail__title">基本信息</h3>
        <dl class="hg-student-detail__grid">
          <div class="hg-student-detail__cell">
            <dt>学号</dt>
            <dd class="tabular">{{ detail.student.student_id }}</dd>
          </div>
          <div class="hg-student-detail__cell">
            <dt>姓名</dt>
            <dd>{{ detail.student.name }}</dd>
          </div>
          <div class="hg-student-detail__cell">
            <dt>性别</dt>
            <dd>{{ detail.student.gender ?? '—' }}</dd>
          </div>
          <div class="hg-student-detail__cell">
            <dt>学院</dt>
            <dd>{{ detail.student.college ?? '—' }}</dd>
          </div>
          <div class="hg-student-detail__cell">
            <dt>班级</dt>
            <dd>{{ detail.student.class_name ?? '—' }}</dd>
          </div>
          <div class="hg-student-detail__cell">
            <dt>年级</dt>
            <dd>{{ detail.student.grade ?? '—' }}</dd>
          </div>
          <div class="hg-student-detail__cell">
            <dt>宿舍</dt>
            <dd>{{ detail.student.dorm_id ?? '—' }}</dd>
          </div>
          <div class="hg-student-detail__cell">
            <dt>手机号</dt>
            <dd class="tabular">{{ maskPhone(detail.student.phone) }}</dd>
          </div>
        </dl>
      </section>
      <section class="hg-student-detail__section">
        <h3 class="hg-student-detail__title">名下车辆（{{ detail.vehicles.length }}）</h3>
        <EmptyState
          v-if="detail.vehicles.length === 0"
          title="暂无绑定车辆"
          description="可在待识别车辆池中绑定该学生的车辆。"
        />
        <ul v-else class="hg-student-detail__vehicle-list">
          <li
            v-for="vehicle in detail.vehicles"
            :key="vehicle.vehicle_id"
            class="hg-student-detail__vehicle-item"
          >
            <span class="tabular">{{ vehicle.vehicle_id }}</span>
            <span>{{ vehicle.plate_no ?? '无牌' }}</span>
            <span>{{ bindTypeLabel(vehicle.owner_bind_type) }}</span>
          </li>
        </ul>
      </section>
      <section class="hg-student-detail__section">
        <h3 class="hg-student-detail__title">近期身份判定（{{ detail.resolutions.length }}）</h3>
        <EmptyState
          v-if="detail.resolutions.length === 0"
          title="暂无通行记录"
          description="该学生尚未产生身份判定记录。"
        />
        <ElTimeline v-else>
          <ElTimelineItem
            v-for="item in detail.resolutions"
            :key="item.id"
            :timestamp="formatDateTime(item.created_at)"
            placement="top"
          >
            <p class="hg-student-detail__timeline-text">
              {{ item.vehicle_id ?? '未知车辆' }} · {{ identityMethodLabel(item.method) }} ·
              <span class="tabular">{{ formatConfidencePercent(item.confidence) }}</span>
            </p>
          </ElTimelineItem>
        </ElTimeline>
      </section>
      <section class="hg-student-detail__section">
        <h3 class="hg-student-detail__title">积分流水</h3>
        <EmptyState title="暂无积分流水" description="积分域接入后在此展示加减分明细。" />
      </section>
    </div>
  </ElDrawer>
</template>

<script setup lang="ts">
import { ElButton, ElDrawer, ElSkeleton, ElTimeline, ElTimelineItem } from 'element-plus'
import EmptyState from '@/components/EmptyState.vue'
import type { StudentDetail } from '@/api/students'
import {
  bindTypeLabel,
  formatConfidencePercent,
  formatDateTime,
  identityMethodLabel,
  maskPhone,
} from './studentsFormat'

defineProps<{
  open: boolean
  detail: StudentDetail | null
  detailLoading: boolean
  detailError: string | null
}>()

const emit = defineEmits<{
  'update:open': [value: boolean]
  retry: []
}>()
</script>

<style scoped lang="scss">
.hg-student-detail__error {
  color: var(--color-danger);
}
.hg-student-detail__section {
  margin-bottom: var(--space-5);
}
.hg-student-detail__title {
  margin: 0 0 var(--space-2);
  font-size: var(--text-headline-size);
  font-weight: var(--text-headline-weight);
  color: var(--color-text);
}
.hg-student-detail__grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: var(--space-3);
  margin: 0;
}
.hg-student-detail__vehicle-list {
  margin: 0;
  padding: 0;
  list-style: none;
}
</style>
