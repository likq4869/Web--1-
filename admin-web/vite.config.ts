// ===========================================================================
// Vite 配置 —— 路径别名、开发代理、SASS 令牌注入
// ===========================================================================

import { fileURLToPath, URL } from 'node:url'
import { defineConfig, loadEnv } from 'vite'
import vue from '@vitejs/plugin-vue'
import AutoImport from 'unplugin-auto-import/vite'
import Components from 'unplugin-vue-components/vite'
import { ElementPlusResolver } from 'unplugin-vue-components/resolvers'

// Vite 5+ 的 __dirname 替代方案
const resolvePath = (relative: string): string => fileURLToPath(new URL(relative, import.meta.url))

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), '')
  const apiTarget = env.VITE_API_PROXY_TARGET ?? 'http://127.0.0.1:8000'

  return {
    plugins: [
      vue(),
      AutoImport({
        imports: ['vue', 'vue-router', 'pinia'],
        dts: 'src/types/auto-imports.d.ts',
        eslintrc: { enabled: false },
      }),
      Components({
        dts: 'src/types/components.d.ts',
        resolvers: [ElementPlusResolver({ importStyle: 'sass' })],
        dirs: ['src/components'],
      }),
    ],

    resolve: {
      alias: {
        '@': resolvePath('./src'),
        '@styles': resolvePath('./src/styles'),
      },
    },

    css: {
      preprocessorOptions: {
        scss: {
          // 自动注入设计令牌，避免每个组件重复 @use
          additionalData: `@use "@/styles/design-tokens.scss" as *;\n`,
          // 静默 Element Plus 内部告警
          silenceDeprecations: ['legacy-js-api', 'import', 'mixed-decls', 'global-builtin'],
        },
      },
    },

    server: {
      port: 5173,
      strictPort: false,
      proxy: {
        '/api': {
          target: apiTarget,
          changeOrigin: true,
        },
        '/health': {
          target: apiTarget,
          changeOrigin: true,
        },
      },
    },

    build: {
      target: 'es2020',
      sourcemap: mode !== 'production',
      chunkSizeWarningLimit: 1200,
      rollupOptions: {
        output: {
          // Rolldown 要求 manualChunks 为函数形式
          manualChunks(id: string) {
            if (!id.includes('node_modules')) return undefined
            if (id.includes('echarts') || id.includes('zrender')) return 'charts'
            if (id.includes('element-plus')) return 'element'
            if (
              id.includes('/vue/') ||
              id.includes('vue-router') ||
              id.includes('/pinia/') ||
              id.includes('@vue/')
            ) {
              return 'vue'
            }
            return undefined
          },
        },
      },
    },
  }
})
