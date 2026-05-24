# 005 · Tasks

## Phase 1 — Backend store

- [x] **T1.1** `artifacts/models.py` — `Artifact` pydantic model + `content_type_for`
- [x] **T1.2** `artifacts/store.py` — `ArtifactStore` ABC + `LocalFileArtifactStore` + `default_artifact_store`（sha2 shard + atomic manifest）
- [x] **T1.3** `artifacts/store.py` — `RunArtifacts` facade
- [x] **T1.4** `data/` 加进 `.gitignore`

## Phase 2 — Events + injection

- [x] **T2.1** `schemas/events.py` — `EventType += artifact_written / await_review`
- [x] **T2.2** `agents/base.py` — `artifacts: RunArtifacts | None`
- [x] **T2.3** `agents/harness.py` — 入口注入 `RunArtifacts`
- [x] **T2.4** harness 主循环对 `await_review`：双写 + auto-approve + tag

## Phase 3 — API

- [x] **T3.1** `api/artifacts.py` — `GET .../artifacts` 列表 + `GET .../{name}` 下载
- [x] **T3.2** `main.py` 挂载 router（路径穿越映射到 400，缺失映射到 404）

## Phase 4 — Frontend

- [x] **T4.1** `lib/api.ts` — `Artifact` / `ArtifactRef` / `listArtifacts` / `artifactUrl` / `fetchArtifactText`
- [x] **T4.2** `components/agent/Artifacts.tsx` — 列表 + 右抽屉 viewer（markdown/json/text/binary）
- [x] **T4.3** `app/runs/[id]/view.tsx` — 从 events 提 ArtifactRef，加 Artifacts 节
- [x] **T4.4** `components/agent/Trace.tsx` — 渲染 `artifact_written` / `await_review` 事件 + 加色 dot

## Phase 5 — Wire skills to demo

- [x] **T5.1** research：累积 delta → 跑完写 `final-research.md` + yield `artifact_written`
- [x] **T5.2** earnings：同上写 `final-earnings.md`

## Phase 6 — Verify

- [x] **T6.1** module 烟测：write/list/read 通；路径穿越被拒
- [x] **T6.2** research 真跑 → `final-research.md` 含 LLM 真引用的 mock 数据（120.08 元）
- [x] **T6.3** earnings 真跑 → `final-earnings.md` 含 `[UNSOURCED]` 触发
- [x] **T6.4** await_review dummy skill：auto-approve + tag
- [x] **T6.5** 路径安全：encoded / raw / valid / missing 4 种 case 全对
- [x] **T6.6** ruff + 前端 typecheck 通过

## Phase 7 — Spec

- [x] **T7.1** `openspec/specs/artifacts/spec.md` 全文写完
- [x] **T7.2** `openspec/specs/harness/spec.md` 加 "Skill injection (M3+M5)" 段 + await_review 段；引用 artifacts spec
- [ ] **T7.3** 移到 archive（待整 change 完成）

## 后续（不在本 change）

- 005.2 真实 await_review 拦截 + `POST /api/runs/{id}/approve` 端点 + skill 中断恢复
- 005.3 Retention policy（默认 30 天自动清）
- 005.4 S3 / Vercel Blob backend
