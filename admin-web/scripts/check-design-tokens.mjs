#!/usr/bin/env node
/**
 * 设计令牌门禁 —— Design System v1.1 (design.md §1.5 / §3.2 / §4.3 / §4.4 / §9.2)
 *
 * 规则：
 * - 色板 / 字重 / 阻尼必须走 design-tokens.scss，禁止组件写字面量；
 * - ECharts 需要具体色值，只能经 charts/theme.ts 的 token(name, fallback) 读取，
 *   因此 token 读取行的回退色不算违规（单点收敛在 theme.ts + Dashboard resolveColor）。
 * - Dashboard 的 `return resolved ||` 是 ECharts 运行时回退（无 computedStyle 时），放行。
 */
import { readdirSync, readFileSync, statSync } from 'node:fs'
import { fileURLToPath } from 'node:url'
import { dirname, join } from 'node:path'

const HERE = dirname(fileURLToPath(import.meta.url))
const SRC = join(HERE, '..', 'src')
const ALLOW_HEX_FILES = new Set(['styles/design-tokens.scss', 'styles/element-theme.scss'])
const HEX_RE = /#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})\b/
const GRADIENT_RE = /linear-gradient\s*\(|radial-gradient\s*\(/i
const IMPORTANT_RE = /!important/
const CUBIC_RE = /cubic-bezier\s*\(/
const BACKDROP_RE = /backdrop-filter\s*:/
const FONT_WEIGHT_NUM_RE = /font-weight\s*:\s*(400|500|600|700)\s*;/
const MAX_FILE_LINES = 400
const MAX_STYLE_LINES = 100

function walk(dir, out = []) {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name)
    if (statSync(p).isDirectory()) walk(p, out)
    else if (/\.(vue|scss|ts)$/.test(name)) out.push(p)
  }
  return out
}

function styleBlockLines(vueSource) {
  const m = vueSource.match(/<style[^>]*>([\s\S]*?)<\/style>/)
  if (!m) return 0
  return m[1].split('\n').length
}

const targets = walk(SRC)
const errors = []

for (const abs of targets) {
  const rel = abs.slice(SRC.length + 1).replace(/\\/g, '/')
  const text = readFileSync(abs, 'utf8')
  const lines = text.split('\n')

  if (rel.endsWith('.vue') && lines.length > MAX_FILE_LINES) {
    errors.push(`${rel}: 单文件 ${lines.length} 行，超出 ${MAX_FILE_LINES} 行（请拆分子组件/composable/_styles）`)
  }
  if (rel.endsWith('.vue')) {
    const n = styleBlockLines(text)
    if (n > MAX_STYLE_LINES) {
      errors.push(`${rel}: <style> 块 ${n} 行，超出 ${MAX_STYLE_LINES} 行（请抽到独立 .scss）`)
    }
  }

  lines.forEach((line, idx) => {
    const no = idx + 1
    const trimmed = line.trim()
    if (!trimmed || trimmed.startsWith('//') || trimmed.startsWith('*')) return

    if (GRADIENT_RE.test(line)) errors.push(`${rel}:${no}: 禁止渐变填充（design.md §3.1），请用纯色 + 透明度`)
    if (IMPORTANT_RE.test(line)) errors.push(`${rel}:${no}: 禁止 !important，请用层叠顺序/特异性解决`)
    if (BACKDROP_RE.test(line)) errors.push(`${rel}:${no}: 禁止 backdrop-filter（毛玻璃），请用实心 surface 色阶`)
    if (CUBIC_RE.test(line) && !rel.endsWith('design-tokens.scss')) {
      errors.push(`${rel}:${no}: 禁止 cubic-bezier 字面量，请引用 var(--ease-overdamped)/var(--ease-underdamped) 等令牌`)
    }
    if (FONT_WEIGHT_NUM_RE.test(line) && !rel.endsWith('design-tokens.scss')) {
      errors.push(`${rel}:${no}: font-weight 禁止数字字面量，请引用 var(--font-weight-*) 令牌`)
    }
    if (HEX_RE.test(line)) {
      if (ALLOW_HEX_FILES.has(rel)) return
      if (/token\s*\(|getComputedStyle|getPropertyValue|resolved\s*\|\||--color-/.test(line)) return
      errors.push(`${rel}:${no}: 发现原始色值 ${trimmed.slice(0, 80)}，请引用 var(--color-*) 令牌`)
    }
  })
}

if (errors.length) {
  console.error(`[check:tokens] 发现 ${errors.length} 处设计令牌违规：`)
  for (const e of errors) console.error(`  - ${e}`)
  process.exit(1)
}
console.log(`[check:tokens] 通过：${targets.length} 个文件，无令牌违规。`)
