// ===========================================================================
// ESLint flat config —— Vue 3 + TypeScript
// 规则重点：
//   - vue/multi-word-component-names  组件名必须多词
//   - vue/require-default-prop        所有 prop 必须有默认值
//   - @typescript-eslint/no-explicit-any  禁止 any
//   - @typescript-eslint/consistent-type-imports  统一类型导入写法
// ===========================================================================

import js from '@eslint/js'
import pluginVue from 'eslint-plugin-vue'
import pluginTs from '@typescript-eslint/eslint-plugin'
import tsParser from '@typescript-eslint/parser'
import vueParser from 'vue-eslint-parser'
import prettierConfig from 'eslint-config-prettier'
import prettierPlugin from 'eslint-plugin-prettier'
import globals from 'globals'

export default [
  {
    ignores: [
      'dist/**',
      'node_modules/**',
      'coverage/**',
      'src/api/generated/**',
      // unplugin 自动生成的类型声明，由插件维护，不参与 lint
      'src/types/auto-imports.d.ts',
      'src/types/components.d.ts',
      'package-lock.json',
      '*.json',
      '*.md',
      // SCSS 由 Prettier 负责格式化，ESLint 不解析
      '**/*.scss',
    ],
  },

  js.configs.recommended,

  // ---------- Vue ----------
  ...pluginVue.configs['flat/recommended'],

  // ---------- TypeScript ----------
  {
    files: ['**/*.ts', '**/*.tsx'],
    languageOptions: {
      parser: tsParser,
      parserOptions: {
        ecmaVersion: 'latest',
        sourceType: 'module',
      },
      globals: {
        ...globals.browser,
        ...globals.es2021,
      },
    },
    plugins: {
      '@typescript-eslint': pluginTs,
    },
    rules: {
      ...pluginTs.configs.recommended.rules,
      // TypeScript 编译器已覆盖未定义变量检测，关闭 ESLint 的 no-undef
      'no-undef': 'off',
      // 基础规则不识别 TS 类型签名中的参数名，统一交给 @typescript-eslint 版本
      'no-unused-vars': 'off',
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/consistent-type-imports': [
        'error',
        { prefer: 'type-imports', fixStyle: 'inline-type-imports' },
      ],
      '@typescript-eslint/explicit-module-boundary-types': 'error',
      'no-console': ['warn', { allow: ['warn', 'error'] }],
      eqeqeq: ['error', 'always', { null: 'ignore' }],
    },
  },

  // ---------- .vue 文件 ----------
  {
    files: ['**/*.vue'],
    languageOptions: {
      parser: vueParser,
      parserOptions: {
        parser: tsParser,
        ecmaVersion: 'latest',
        sourceType: 'module',
        extraFileExtensions: ['.vue'],
      },
      globals: {
        ...globals.browser,
        ...globals.es2021,
      },
    },
    plugins: {
      '@typescript-eslint': pluginTs,
    },
    rules: {
      // 组件名必须多词（避免与 HTML 元素冲突）
      'vue/multi-word-component-names': 'error',
      // 所有 prop 必须有默认值
      'vue/require-default-prop': 'error',
      // 属性顺序与换行
      'vue/attributes-order': 'warn',
      'vue/html-self-closing': ['warn', { html: { void: 'always' } }],
      'vue/singleline-html-element-content-newline': 'off',
      'vue/no-unused-vars': 'error',
      'no-undef': 'off',
      // 基础规则不识别 TS 类型签名中的参数名，统一交给 @typescript-eslint 版本
      'no-unused-vars': 'off',
      // 禁止在组件内使用 any
      '@typescript-eslint/no-explicit-any': 'error',
      '@typescript-eslint/no-unused-vars': [
        'error',
        { argsIgnorePattern: '^_', varsIgnorePattern: '^_' },
      ],
      '@typescript-eslint/consistent-type-imports': [
        'error',
        { prefer: 'type-imports', fixStyle: 'inline-type-imports' },
      ],
      'no-console': ['warn', { allow: ['warn', 'error'] }],
    },
  },

  // ---------- 视图文件豁免多词组件名 ----------
  // 视图按路由语义命名（dashboard/Index、error/404），
  // 文件名已隐含父级语义，不构成命名冲突风险。
  {
    files: ['src/views/**/*.vue'],
    rules: {
      'vue/multi-word-component-names': 'off',
    },
  },

  // ---------- Node 脚本（门禁/构建脚本走 Node 运行时） ----------
  {
    files: ['scripts/**/*.mjs', 'scripts/**/*.cjs'],
    languageOptions: {
      globals: {
        ...globals.node,
      },
    },
  },

  // ---------- Prettier 放最后，覆盖冲突的格式规则 ----------
  prettierConfig,
  {
    files: ['**/*.{ts,tsx,vue,scss}'],    plugins: {
      prettier: prettierPlugin,
    },
    rules: {
      'prettier/prettier': 'error',
    },
  },
]
