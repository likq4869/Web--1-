# ===========================================================================
# 从后端 OpenAPI 自动生成 TypeScript 类型
#
# 用途：保证前后端接口契约同步，避免手写重复类型。
# 后端未就绪时脚本优雅失败（exit 0），不阻塞前端开发。
# ===========================================================================
#!/usr/bin/env bash
set -uo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
OUT_DIR="${PROJECT_ROOT}/src/api/generated"
OUT_FILE="${OUT_DIR}/schema.ts"

# 后端地址：优先环境变量，默认本地开发端口
API_BASE="${VITE_API_BASE_URL:-http://127.0.0.1:8000}"
OPENAPI_URL="${API_BASE%/api}/openapi.json"

mkdir -p "${OUT_DIR}"

echo "[gen-api] 目标: ${OPENAPI_URL}"

# 检查后端是否可达
if ! curl -fsS --max-time 10 "${OPENAPI_URL}" -o "${OUT_DIR}/openapi.json" 2>/dev/null; then
  echo "[gen-api] 后端 OpenAPI 暂不可达，跳过类型生成（不阻塞开发）。"
  exit 0
fi

echo "[gen-api] 已获取 OpenAPI 规范，开始生成类型..."

if npx --no-install openapi-typescript "${OUT_DIR}/openapi.json" \
  -o "${OUT_FILE}" \
  --alphabetize 2>/dev/null; then
  echo "[gen-api] 类型已生成: ${OUT_FILE}"
else
  echo "[gen-api] 生成失败，保留既有 schema.ts。"
  exit 0
fi
