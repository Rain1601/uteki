# @uteki/shared-types

OpenAPI 生成的 TypeScript 类型。前端通过 `import type { paths } from "@uteki/shared-types"` 拿到端到端类型。

## 生成

api 服务必须先在 `http://localhost:8000` 跑起来：

```bash
make api          # 起后端
pnpm --filter @uteki/shared-types generate
```

或者用根目录的 `make types`。
