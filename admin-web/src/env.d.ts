/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** API 基础路径（开发环境走 Vite 代理） */
  readonly VITE_API_BASE_URL?: string
  /** 开发代理的后端地址 */
  readonly VITE_API_PROXY_TARGET?: string
  /** 应用标题 */
  readonly VITE_APP_TITLE?: string
}

interface ImportMeta {
  readonly env: ImportMetaEnv
}
