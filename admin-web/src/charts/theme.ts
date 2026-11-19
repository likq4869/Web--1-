// ===========================================================================
// ECharts 统一主题 —— 从设计令牌读取，禁止硬编码色值
//
// 规范依据：design.md §8.1 ~ §8.5
//   · 图表色板按语义顺序（主色 / 成功 / 警告 / 危险 / 中性 / L2 橙红）
//   · 禁止渐变填充 —— 面积图用纯色低透明度
//   · 网格线极淡、轴线不显示
//   · 环形图薄环、圆角 2px、中心显示总计
// ===========================================================================

import type { EChartsOption } from 'echarts'

/** 读取 CSS 变量的实际色值（ECharts 需要具体颜色，不能用 var()） */
function token(name: string, fallback: string): string {
  if (typeof window === 'undefined') return fallback
  const value = window.getComputedStyle(document.documentElement).getPropertyValue(name)
  return value.trim() || fallback
}

/** 图表色板 —— 语义顺序固定 */
export function chartPalette(): string[] {
  return [
    token('--color-primary', '#007aff'),
    token('--color-success', '#1f9d46'),
    token('--color-warning', '#ff9500'),
    token('--color-danger', '#d92d20'),
    token('--color-text-3', '#8e8e93'),
    token('--color-deep-warning', '#e8590c'), // L2 深橙（第五色，语义固定）
  ]
}

/** 基础文字样式 */
export function chartTextStyle(): {
  color: string
  fontFamily: string
  fontSize: number
} {
  return {
    color: token('--color-text-3', '#8e8e93'),
    fontFamily: token('--font-family-base', 'system-ui, sans-serif'),
    fontSize: 12,
  }
}

/** 网格配置 —— 网格线极淡、轴线不显示 */
export function chartGrid(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    left: 8,
    right: 12,
    top: 24,
    bottom: 8,
    containLabel: true,
    ...overrides,
  }
}

/** 通用 Tooltip —— 悬浮层边框属白名单（需与背后明确可分） */
export function chartTooltip(): Record<string, unknown> {
  return {
    trigger: 'axis',
    backgroundColor: token('--color-surface', '#ffffff'),
    borderColor: token('--color-sep-strong', '#e5e5ea'),
    borderWidth: 1,
    padding: [8, 12],
    textStyle: {
      color: token('--color-text', '#1c1c1e'),
      fontSize: 13,
      fontFamily: token('--font-family-base', 'system-ui, sans-serif'),
    },
    axisPointer: {
      type: 'cross',
      lineStyle: { color: token('--color-sep-strong', '#e5e5ea'), width: 1 },
      crossStyle: { color: token('--color-sep-strong', '#e5e5ea'), width: 1 },
      label: { backgroundColor: token('--color-text-3', '#8e8e93') },
    },
  }
}

/** 分类轴（X 轴） */
export function chartCategoryAxis(data: string[]): Record<string, unknown> {
  return {
    type: 'category',
    data,
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: token('--color-text-3', '#8e8e93'), fontSize: 12 },
    splitLine: { show: false },
  }
}

/** 数值轴（Y 轴） */
export function chartValueAxis(overrides: Record<string, unknown> = {}): Record<string, unknown> {
  return {
    type: 'value',
    axisLine: { show: false },
    axisTick: { show: false },
    axisLabel: { color: token('--color-text-3', '#8e8e93'), fontSize: 12 },
    splitLine: {
      show: true,
      lineStyle: { color: token('--color-sep', '#f2f2f7'), width: 1 },
    },
    ...overrides,
  }
}

/**
 * 折线 / 面积图选项。
 *
 * 面积填充为纯色低透明度（非渐变）；线宽 2px；平滑 0.2。
 */
export function lineAreaOption(params: {
  labels: string[]
  values: number[]
  color?: string
  valueFormatter?: (value: number) => string
}): EChartsOption {
  const color = params.color ?? token('--color-primary', '#007aff')
  const formatter = params.valueFormatter ?? ((value: number) => String(value))
  return {
    color: chartPalette(),
    textStyle: chartTextStyle(),
    grid: chartGrid(),
    tooltip: {
      ...chartTooltip(),
      valueFormatter: (value: unknown) => formatter(Number(value)),
    },
    xAxis: chartCategoryAxis(params.labels),
    yAxis: chartValueAxis(),
    series: [
      {
        type: 'line',
        name: '佩戴率',
        data: params.values,
        smooth: 0.2,
        showSymbol: false,
        lineStyle: { width: 2, color },
        itemStyle: { color },
        // 纯色 8% 透明度填充，禁止渐变
        areaStyle: { color, opacity: 0.08 },
        animationDuration: 300,
      },
    ],
  }
}

/**
 * 环形图选项。
 *
 * 薄环（线宽 12px）、半径 ['62%','82%']、圆角 2px、中心显示总计。
 */
export function donutOption(params: {
  items: Array<{ name: string; value: number; color: string }>
  total: number
  totalLabel: string
}): EChartsOption {
  const text = chartTextStyle()
  return {
    color: params.items.map((item) => item.color),
    textStyle: text,
    tooltip: {
      ...chartTooltip(),
      trigger: 'item',
      valueFormatter: (value: unknown) => String(value),
    },
    series: [
      {
        type: 'pie',
        radius: ['62%', '82%'],
        avoidLabelOverlap: true,
        label: { show: false },
        labelLine: { show: false },
        itemStyle: {
          borderRadius: 2,
          borderColor: token('--color-surface', '#fff'),
          borderWidth: 1,
        },
        data: params.items.map((item) => ({ name: item.name, value: item.value })),
      },
    ],
    graphic: {
      type: 'group',
      left: 'center',
      top: 'center',
      children: [
        {
          type: 'text',
          style: {
            text: String(params.total),
            fill: token('--color-text', '#1c1c1e'),
            fontSize: 32,
            fontWeight: 700,
            fontFamily: token('--font-family-base', 'system-ui, sans-serif'),
            textAlign: 'center',
            textVerticalAlign: 'middle',
          },
        },
        {
          type: 'text',
          style: {
            text: params.totalLabel,
            fill: token('--color-text-3', '#8e8e93'),
            fontSize: 12,
            fontFamily: token('--font-family-base', 'system-ui, sans-serif'),
            textAlign: 'center',
            textVerticalAlign: 'middle',
          },
        },
      ],
    },
  }
}

/**
 * 横向条形图选项（违规时段分布 / Top 班级）。
 */
export function barOption(params: {
  categories: string[]
  values: number[]
  color?: string
  valueFormatter?: (value: number) => string
}): EChartsOption {
  const color = params.color ?? token('--color-danger', '#d92d20')
  const formatter = params.valueFormatter ?? ((value: number) => String(value))
  return {
    color: chartPalette(),
    textStyle: chartTextStyle(),
    grid: chartGrid({ left: 8, right: 24, top: 8, bottom: 8 }),
    tooltip: {
      ...chartTooltip(),
      trigger: 'item',
      valueFormatter: (value: unknown) => formatter(Number(value)),
    },
    xAxis: chartValueAxis({ splitLine: { show: false } }),
    yAxis: {
      type: 'category',
      data: params.categories,
      axisLine: { show: false },
      axisTick: { show: false },
      axisLabel: { color: token('--color-text-3', '#8e8e93'), fontSize: 12 },
      splitLine: { show: false },
    },
    series: [
      {
        type: 'bar',
        data: params.values,
        itemStyle: { color, borderRadius: [0, 2, 2, 0] },
        barMaxWidth: 14,
        animationDuration: 300,
      },
    ],
  }
}
