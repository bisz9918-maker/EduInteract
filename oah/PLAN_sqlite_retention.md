# SQLite Metadata Retention Service 实现计划

## 1. Context

OAH 的 SQLite 存储没有 retention 清理机制，`message.delta` 流式事件无限堆积在 `session_events` 表中。当引擎调用 `listSince(sessionId)` 无 cursor/limit 加载全量事件时，V8 heap OOM 导致进程崩溃。即使设了 128GB heap 也不够。

**OOM 触发链路**：
```
LLM 流式输出 → 每 token 产生 message.delta → 写入 session_events 表（无上限）
→ buildEngineMessagesForSession() 调用 listSince(sessionId) 无 cursor/limit
→ SQLite 返回所有 payload → JSON.parse 解析为 JS 对象 → V8 heap 膨胀
→ 超过 --max-old-space-size → FatalProcessOutOfMemory → SIGABRT
```

**已有 6 个实例中 4 个因此崩溃**（instance 1/2/3/5），state 目录分别达到 438MB/6.5GB/31GB/24GB。

## 2. 安全性分析

### 2.1 在 SQL 层面排除 delta 不影响 agent 行为

**关键前提**：`message.delta` 的唯一两个全量加载调用点在 `engine-message-sync.ts`（第 36 行和第 77 行），目的是构建 engine messages。

**当 delta 不存在时的行为**：
- `projectRunEngineMessages()` (engine-messages.ts:302-304)：当某 run 的 events 为空时，走 `toEngineMessages(messages)` 路径，直接从 `messages` 表构建 engine message
- 已完成 run：`messages` 表有完整内容 → 输出与有 delta 时一致
- 运行中 run：`messages` 表有已持久化的消息 → 同样能正确构建

**不受影响的功能**：
- SSE 流式显示：通过 `SessionEventStore.subscribe()` 实时获取单条 delta，不走 `listSince`
- LLM 推理：上下文来自 `messages` 表，不是 engine messages
- API 客户端查询历史事件：`engine-service.ts:838` 的 `listSince` 加了 `excludeEventTypes` 参数后默认不排除，向后兼容

### 2.2 删除已完成 run 的 delta 不影响 agent 行为

- Run 完成后，最终消息内容已持久化在 `messages` 表中
- 只删除 `message.delta`，**保留** `message.completed`、`run.completed`、`run.failed`、`run.cancelled` 等事件
- 运行中 run 的 delta 绝不删除

## 3. 两道防线

| 防线 | 作用 | 覆盖场景 |
|------|------|----------|
| **防线 1：SQL 层排除 delta** | `listSince` 在 SQL 查询中排除 `message.delta`，数据不进入 V8 heap | 已完成 run、运行中长 run、单步超长思考 |
| **防线 2：Retention 清理** | 定期删除已完成 run 的 delta，释放磁盘 | SQLite 文件无限增长 |

防线 1 是**根因修复**：delta 在 SQL 层被排除，无论 run 是否完成都不会 OOM。
防线 2 是**磁盘清理**：防止 SQLite 文件无限增长。

## 4. 修改文件清单

| 文件 | 修改内容 |
|------|----------|
| `packages/engine-core/src/types/storage.ts` | `SessionEventStore.listSince` 增加 `excludeEventTypes` 参数 |
| `packages/storage-sqlite/src/repositories.ts` | SQLite `listSince` 实现 SQL 层排除 + 添加 `deleteDeltasByRunIds` |
| `packages/storage-postgres/src/repositories.ts` | Postgres `listSince` 实现排除（保持接口一致） |
| `packages/storage-redis/src/fanout-session-event-store.ts` | 透传 `excludeEventTypes` |
| `apps/server/src/bootstrap/service-routed-postgres.ts` | 透传 `excludeEventTypes` |
| `packages/engine-core/src/engine/engine-message-sync.ts` | 调用 `listSince` 时传 `excludeEventTypes: ["message.delta"]` |
| `packages/engine-core/src/engine-service.ts` | 透传 `excludeEventTypes` |
| `packages/storage-sqlite/src/coordinator.ts` | 添加 `listTerminalRunIds` 方法 |
| `packages/storage-sqlite/src/index.ts` | 在 `SQLiteRuntimePersistence` 接口暴露 `coordinator` |
| `apps/server/src/sqlite-metadata-retention.ts` | **新建** - `SQLiteMetadataRetentionService` 类 |
| `apps/server/src/bootstrap.ts` | 添加配置解析 + 实例化 + 启动/关闭钩子 |

## 5. 实现步骤

### Step 1（根因修复）: `listSince` 增加 `excludeEventTypes` 参数

**核心思路**：在 SQL 查询层面排除 delta，让它们根本不进入 V8 heap。JS 端 `filter()` 过滤太晚——数据已经加载到内存了。

#### 1a. 修改 `SessionEventStore` 接口

**文件**: `packages/engine-core/src/types/storage.ts` (第 220-225 行)

```typescript
// 之前:
export interface SessionEventStore {
  append(input: Omit<SessionEvent, "id" | "cursor" | "createdAt">): Promise<SessionEvent>;
  deleteById(eventId: string): Promise<void>;
  listSince(sessionId: string, cursor?: string, runId?: string, limit?: number): Promise<SessionEvent[]>;
  subscribe(sessionId: string, listener: (event: SessionEvent) => void): () => void;
}

// 之后:
export interface SessionEventStore {
  append(input: Omit<SessionEvent, "id" | "cursor" | "createdAt">): Promise<SessionEvent>;
  deleteById(eventId: string): Promise<void>;
  listSince(
    sessionId: string,
    cursor?: string,
    runId?: string,
    limit?: number,
    excludeEventTypes?: ReadonlyArray<string>
  ): Promise<SessionEvent[]>;
  subscribe(sessionId: string, listener: (event: SessionEvent) => void): () => void;
}
```

`excludeEventTypes` 默认 `undefined`（不排除），完全向后兼容。

#### 1b. 修改 SQLite `listSince` 实现

**文件**: `packages/storage-sqlite/src/repositories.ts` (第 663-690 行)

在 SQL 查询中动态添加排除条件：

```typescript
async listSince(
  sessionId: string,
  cursor?: string,
  runId?: string,
  limit?: number,
  excludeEventTypes?: ReadonlyArray<string>
): Promise<SessionEvent[]> {
  const handle = await this.#coordinator.getSessionHandle(sessionId);
  const parsedCursor = cursor ? Number.parseInt(cursor, 10) : -1;
  const normalizedCursor = Number.isFinite(parsedCursor) && parsedCursor >= -1 ? parsedCursor : -1;
  const readLimit = Number.isFinite(limit) && limit !== undefined ? Math.max(1, Math.floor(limit)) : undefined;

  // 构建 SQL：当 excludeEventTypes 非空时，添加 json_extract 排除条件
  const excludeClause = excludeEventTypes && excludeEventTypes.length > 0
    ? `and json_extract(payload, '$.event') not in (${excludeEventTypes.map(() => '?').join(', ')})`
    : '';

  let rows: JsonRow[];
  if (runId) {
    const params = [sessionId, normalizedCursor, runId, ...excludeEventTypes ?? []];
    rows = coerceRows<JsonRow>(
      handle.db
        .prepare(
          `select payload from session_events
           where session_id = ? and cursor > ? and run_id = ?
           ${excludeClause}
           order by cursor asc
           ${readLimit ? "limit ?" : ""}`
        )
        .all(...(readLimit ? [...params, readLimit] : params))
    );
  } else {
    const params = [sessionId, normalizedCursor, ...excludeEventTypes ?? []];
    rows = coerceRows<JsonRow>(
      handle.db
        .prepare(
          `select payload from session_events
           where session_id = ? and cursor > ?
           ${excludeClause}
           order by cursor asc
           ${readLimit ? "limit ?" : ""}`
        )
        .all(...(readLimit ? [...params, readLimit] : params))
    );
  }
  return rows.map((row) => parseJson<SessionEvent>(row.payload));
}
```

**性能说明**：`json_extract(payload, '$.event')` 会扫描匹配行，但由于前置条件 `session_id` + `cursor` 已通过索引 `session_events_session_cursor_idx` 缩小范围，且 `message.delta` 通常占事件总量 90%+，排除后返回行数极少，实际网络/内存开销大幅降低。

#### 1c. 修改 Postgres `listSince` 实现

**文件**: `packages/storage-postgres/src/repositories.ts` (第 810 行)

Postgres 有独立的 `event` 列，直接用 `event NOT IN (...)` 过滤，比 SQLite 的 `json_extract` 更高效。

```typescript
async listSince(
  sessionId: string,
  cursor?: string,
  runId?: string,
  limit?: number,
  excludeEventTypes?: ReadonlyArray<string>
): Promise<SessionEvent[]> {
  // ... 现有逻辑 ...
  // 在 WHERE 子句中添加:
  // excludeEventTypes?.length ? sql`and event not in (${sql.join(excludeEventTypes, sql`, `)})` : sql``
}
```

#### 1d. 透传其他实现

- `packages/storage-redis/src/fanout-session-event-store.ts` (第 22-23 行) — 透传 `excludeEventTypes` 给 `#primary.listSince`
- `apps/server/src/bootstrap/service-routed-postgres.ts` (第 1178-1179 行) — 透传给后端
- `packages/engine-core/src/engine-service.ts` (第 838 行) — 透传给 `#sessionEventStore.listSince`

#### 1e. 在 `engine-message-sync.ts` 中使用

**文件**: `packages/engine-core/src/engine/engine-message-sync.ts`

第 36 行修改：
```typescript
// 之前:
this.#sessionEventStore.listSince(sessionId),
// 之后:
this.#sessionEventStore.listSince(sessionId, undefined, undefined, undefined, ["message.delta"]),
```

第 77 行修改：
```typescript
// 之前:
this.#sessionEventStore.listSince(sessionId)
// 之后:
this.#sessionEventStore.listSince(sessionId, undefined, undefined, undefined, ["message.delta"])
```

这样 engine message sync 永远不加载 delta 到内存，从根上消除 OOM。

### Step 2: `SQLiteSessionEventStore.deleteDeltasByRunIds()`

**文件**: `packages/storage-sqlite/src/repositories.ts`

在 `SQLiteSessionEventStore` 类中添加方法：

```typescript
async deleteDeltasByRunIds(runIds: string[]): Promise<number> {
  if (runIds.length === 0) return 0;

  // 按 workspace 分组 runIds，避免重复打开 DB handle
  const runIdsByWorkspace = new Map<string, string[]>();
  for (const runId of runIds) {
    try {
      const workspaceId = await this.#coordinator.getWorkspaceIdForRun(runId);
      const existing = runIdsByWorkspace.get(workspaceId);
      if (existing) { existing.push(runId); }
      else { runIdsByWorkspace.set(workspaceId, [runId]); }
    } catch {
      // run 可能已不存在，跳过
    }
  }

  let totalDeleted = 0;
  for (const [workspaceId, workspaceRunIds] of runIdsByWorkspace) {
    const handle = await this.#coordinator.getWorkspaceHandle(workspaceId);
    const placeholders = workspaceRunIds.map(() => '?').join(', ');
    runInTransaction(handle.db, () => {
      const result = handle.db.prepare(
        `delete from session_events
         where run_id in (${placeholders})
           and json_extract(payload, '$.event') = 'message.delta'`
      ).run(...workspaceRunIds);
      totalDeleted += result.changes;
    });
  }

  // 注意：不清理 session_event_registry，因为 stale registry 条目无害
  // 下次 reindexWorkspace 时会自动清理
  return totalDeleted;
}
```

### Step 3: `SQLitePersistenceCoordinator.listTerminalRunIds()`

**文件**: `packages/storage-sqlite/src/coordinator.ts`

添加方法：

```typescript
listTerminalRunIds(cutoff: string, limit: number): Array<{ runId: string; workspaceId: string }> {
  const results: Array<{ runId: string; workspaceId: string }> = [];
  const workspaces = this.listPersistedWorkspaces();

  for (const workspace of workspaces) {
    if (results.length >= limit) break;

    const handle = this.ensureHandle(workspace.id);
    if (!handle) continue;

    const rows = handle.db.prepare(
      `select id from runs
       where status in ('completed', 'failed', 'cancelled')
         and json_extract(payload, '$.endedAt') is not null
         and json_extract(payload, '$.endedAt') < ?
       order by json_extract(payload, '$.endedAt') asc
       limit ?`
    ).all(cutoff, limit - results.length) as Array<{ id: string }>;

    for (const row of rows) {
      results.push({ runId: row.id, workspaceId: workspace.id });
    }
  }

  return results;
}
```

**注意**：这是同步方法，因为 `DatabaseSync` 是同步的，与 coordinator 其他方法（如 `listPersistedWorkspaces`、`ensureHandle`）一致。

### Step 4: 暴露 coordinator

**文件**: `packages/storage-sqlite/src/index.ts`

在 `SQLiteRuntimePersistence` 接口中添加：
```typescript
readonly coordinator: SQLitePersistenceCoordinator;
```

在 `createSQLiteRuntimePersistence` 返回对象中包含 `coordinator`。

**安全性**：`@oah/storage-sqlite` 的 package.json 是 `private: true`，这是内部 API。

### Step 5: 新建 `SQLiteMetadataRetentionService`

**文件**: `apps/server/src/sqlite-metadata-retention.ts`（新建）

```typescript
import type { SQLitePersistenceCoordinator } from "@oah/storage-sqlite";
import type { SQLiteSessionEventStore } from "@oah/storage-sqlite";
import type { MetadataRetentionLogger } from "./metadata-retention.js";

export interface SQLiteMetadataRetentionOptions {
  coordinator: SQLitePersistenceCoordinator;
  sessionEventStore: SQLiteSessionEventStore;
  intervalMs?: number;
  batchLimit?: number;
  deltaRetentionDays?: number;
  vacuumIntervalRuns?: number;
  logger?: MetadataRetentionLogger;
  now?: () => Date;
}

export interface SQLiteMetadataRetentionRunSummary {
  deltasDeleted: number;
  workspacesScanned: number;
  vacuumed: boolean;
}

const DEFAULT_INTERVAL_MS = 60 * 60 * 1000;  // 1 hour
const DEFAULT_BATCH_LIMIT = 500;
const DEFAULT_DELTA_RETENTION_DAYS = 1;
const DEFAULT_VACUUM_INTERVAL_RUNS = 10;
const MIN_INTERVAL_MS = 60_000;

export class SQLiteMetadataRetentionService {
  readonly #coordinator: SQLitePersistenceCoordinator;
  readonly #sessionEventStore: SQLiteSessionEventStore;
  readonly #intervalMs: number;
  readonly #batchLimit: number;
  readonly #deltaRetentionDays: number;
  readonly #vacuumIntervalRuns: number;
  readonly #logger: MetadataRetentionLogger;
  readonly #now: () => Date;
  #timer: NodeJS.Timeout | undefined;
  #activeRun: Promise<void> | undefined;
  #runCount = 0;

  constructor(options: SQLiteMetadataRetentionOptions) {
    this.#coordinator = options.coordinator;
    this.#sessionEventStore = options.sessionEventStore;
    this.#intervalMs = Math.max(MIN_INTERVAL_MS, options.intervalMs ?? DEFAULT_INTERVAL_MS);
    this.#batchLimit = Math.max(1, Math.min(options.batchLimit ?? DEFAULT_BATCH_LIMIT, 10_000));
    this.#deltaRetentionDays = Math.max(1, options.deltaRetentionDays ?? DEFAULT_DELTA_RETENTION_DAYS);
    this.#vacuumIntervalRuns = Math.max(1, options.vacuumIntervalRuns ?? DEFAULT_VACUUM_INTERVAL_RUNS);
    this.#logger = options.logger ?? {};
    this.#now = options.now ?? (() => new Date());
  }

  start(): void {
    if (this.#timer) return;

    this.#timer = setInterval(() => {
      void this.runOnce().catch((error: unknown) => {
        this.#logger.warn?.("SQLite metadata retention failed.", error);
      });
    }, this.#intervalMs);
    this.#timer.unref?.();

    // 首次立即执行
    void this.runOnce().catch((error: unknown) => {
      this.#logger.warn?.("SQLite metadata retention failed.", error);
    });

    this.#logger.info?.("SQLite metadata retention started.");
  }

  async close(): Promise<void> {
    if (this.#timer) {
      clearInterval(this.#timer);
      this.#timer = undefined;
    }
    if (this.#activeRun) {
      await this.#activeRun.catch(() => undefined);
    }
  }

  async runOnce(): Promise<SQLiteMetadataRetentionRunSummary> {
    if (this.#activeRun) {
      await this.#activeRun;
      return { deltasDeleted: 0, workspacesScanned: 0, vacuumed: false };
    }

    const summary: SQLiteMetadataRetentionRunSummary = {
      deltasDeleted: 0,
      workspacesScanned: 0,
      vacuumed: false
    };

    const task = (async () => {
      const now = this.#now();
      const cutoff = new Date(now.getTime() - this.#deltaRetentionDays * 24 * 60 * 60 * 1000).toISOString();

      // 1. 查找可清理的终态 run
      const terminalRuns = this.#coordinator.listTerminalRunIds(cutoff, this.#batchLimit);
      summary.workspacesScanned = new Set(terminalRuns.map(r => r.workspaceId)).size;

      if (terminalRuns.length > 0) {
        // 2. 删除 delta 事件
        const runIds = terminalRuns.map(r => r.runId);
        summary.deltasDeleted = await this.#sessionEventStore.deleteDeltasByRunIds(runIds);

        // 3. 周期性 VACUUM
        this.#runCount++;
        if (this.#runCount % this.#vacuumIntervalRuns === 0 && summary.deltasDeleted > 0) {
          const workspaceIds = new Set(terminalRuns.map(r => r.workspaceId));
          for (const workspaceId of workspaceIds) {
            try {
              const handle = await this.#coordinator.getWorkspaceHandle(workspaceId);
              handle.db.exec("VACUUM");
            } catch (error) {
              this.#logger.warn?.(`VACUUM failed for workspace ${workspaceId}`, error);
            }
          }
          summary.vacuumed = true;
        }
      }

      if (summary.deltasDeleted > 0) {
        this.#logger.info?.(
          `SQLite metadata retention: deleted ${summary.deltasDeleted} delta events across ${summary.workspacesScanned} workspace(s).`
        );
      }
    })();

    this.#activeRun = task;
    try {
      await task;
      return summary;
    } finally {
      if (this.#activeRun === task) {
        this.#activeRun = undefined;
      }
    }
  }
}
```

### Step 6: 在 bootstrap.ts 中集成

**文件**: `apps/server/src/bootstrap.ts`

#### 6a. 添加配置解析函数

在 `resolvePostgresMetadataRetentionConfig` 函数附近添加：

```typescript
function resolveSqliteMetadataRetentionConfig() {
  return {
    enabled: parseBooleanEnv("OAH_SQLITE_METADATA_RETENTION_ENABLED", true),
    intervalMs: parsePositiveIntEnv("OAH_SQLITE_METADATA_RETENTION_INTERVAL_MS", 60 * 60 * 1000),
    batchLimit: parsePositiveIntEnv("OAH_SQLITE_METADATA_RETENTION_BATCH_LIMIT", 500),
    deltaRetentionDays: parseNonNegativeIntEnv("OAH_SQLITE_DELTA_RETENTION_DAYS", 1),
    vacuumIntervalRuns: parsePositiveIntEnv("OAH_SQLITE_VACUUM_INTERVAL_RUNS", 10)
  };
}
```

**环境变量**：
| 变量 | 默认值 | 说明 |
|------|--------|------|
| `OAH_SQLITE_METADATA_RETENTION_ENABLED` | `true` | 默认开启，因为 OOM 是关键问题 |
| `OAH_SQLITE_METADATA_RETENTION_INTERVAL_MS` | `3600000` | 1 小时 |
| `OAH_SQLITE_METADATA_RETENTION_BATCH_LIMIT` | `500` | 每次最多处理 500 个 run |
| `OAH_SQLITE_DELTA_RETENTION_DAYS` | `1` | 保留 1 天的 delta |
| `OAH_SQLITE_VACUUM_INTERVAL_RUNS` | `10` | 每 10 次清理后 VACUUM |

#### 6b. 添加 lazy module loader

```typescript
let sqliteMetadataRetentionModulePromise: Promise<typeof import("./sqlite-metadata-retention.js")> | undefined;

function loadSqliteMetadataRetentionModule() {
  sqliteMetadataRetentionModulePromise ??= import("./sqlite-metadata-retention.js");
  return sqliteMetadataRetentionModulePromise;
}
```

#### 6c. 实例化和启动

在 Postgres retention 实例化之后（~1948 行）：

```typescript
const sqliteMetadataRetentionConfig = resolveSqliteMetadataRetentionConfig();
const sqliteMetadataRetentionService =
  primaryStorageMode === "sqlite" && sqliteMetadataRetentionConfig.enabled
    ? new (await loadSqliteMetadataRetentionModule()).SQLiteMetadataRetentionService({
        coordinator: persistence.coordinator,
        sessionEventStore: persistence.sessionEventStore as import("@oah/storage-sqlite").SQLiteSessionEventStore,
        intervalMs: sqliteMetadataRetentionConfig.intervalMs,
        batchLimit: sqliteMetadataRetentionConfig.batchLimit,
        deltaRetentionDays: sqliteMetadataRetentionConfig.deltaRetentionDays,
        vacuumIntervalRuns: sqliteMetadataRetentionConfig.vacuumIntervalRuns,
        logger: {
          info(message) { console.info(message); },
          warn(message, error) { console.warn(message, error); }
        }
      })
    : undefined;
sqliteMetadataRetentionService?.start();
```

#### 6d. 关闭钩子

在 `beginDrain()` 函数中添加：
```typescript
await sqliteMetadataRetentionService?.close();
```

在 `close()` 函数的 Promise.all 中添加：
```typescript
sqliteMetadataRetentionService?.close() ?? Promise.resolve(),
```

## 6. 风险和缓解

| 风险 | 缓解措施 |
|------|----------|
| `json_extract` 在 SQLite 查询中性能开销 | 前置 `session_id` + `cursor` 条件已通过索引缩小范围；排除 delta 后返回行数极少 |
| VACUUM 阻塞事件循环 | `DatabaseSync` 是同步的，但 VACUUM 仅每 10 次清理周期执行一次，且只处理有删除的 workspace |
| 删除刚完成 run 的 delta 时 `message.completed` 还没持久化 | `deltaRetentionDays` 默认 1 天，run 完成后 1 天内不会被清理 |
| `excludeEventTypes` 参数破坏向后兼容 | 参数默认 `undefined`，所有现有调用方不需要修改 |
| coordinator `getWorkspaceIdForRun` 对已删除 run 抛异常 | `deleteDeltasByRunIds` 中 try-catch 跳过不存在的 run |
| `SQLiteRuntimePersistence` 暴露 `coordinator` 扩大 API 表面 | 包是 `private: true`，内部使用 |

## 7. 两道防线协作表

| 场景 | 防线 1（SQL 排除 delta） | 防线 2（Retention 清理） |
|------|-------------------------|--------------------------|
| 已完成 run，历史堆积 | engine message sync 不加载 delta → 不 OOM | 定期删除 delta → 释放磁盘 |
| 运行中长 run，大量 delta | engine message sync 不加载 delta → 不 OOM | 不清理运行中 run 的 delta → 安全 |
| 单步超长思考输出 | engine message sync 不加载 delta → 不 OOM | delta 写入磁盘但不进入 V8 heap |
| 新启动，无历史 | 不加载 delta → 内存友好 | 无需清理 |

## 8. 验证方法

1. **编译检查**：`pnpm --dir oah build` 确认 TypeScript 无报错
2. **启动验证**：启动 OAH 实例，确认日志输出 `SQLite metadata retention started`
3. **功能验证**：运行一个完整的 agent task，等 run 完成，再调用 API 获取 engine messages，确认输出正确
4. **清理验证**：等待 retention 周期执行，查询 SQLite 确认已完成 run 的 `message.delta` 被删除，其他事件保留
5. **内存验证**：压测跑 100+ problems，观察内存稳定不再增长
6. **运行中长 run 验证**：启动长时间运行的 agent，确认 engine message sync 期间内存不飙升
