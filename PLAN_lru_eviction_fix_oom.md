# OAH V8 Heap OOM 彻底修复方案：LRU 淘汰无界 Map

## Context

上次修复（`PLAN_sqlite_retention.md`）解决了 `message.delta` 堆积导致的 OOM，已在代码中落地。但 OOM 仍然发生，因为 **`SQLitePersistenceCoordinator` 的 4 个无界 Map 才是真正的内存泄漏源**：

| Map | 代码位置 | 每条大小 | 只增不减的证据 |
|-----|---------|---------|-------------|
| `#workspaceRecords` | coordinator.ts:77 | 5-20KB | `set` 在 upsert，`delete` 仅在显式 deleteWorkspace |
| `#handles` | coordinator.ts:78 | SQLite连接+内核缓冲区 | 打开后永不关闭，直到 workspace 被删 |
| `#sessionIndex` | coordinator.ts:79 | ~100B | set 后永不淘汰 |
| `#runIndex` | coordinator.ts:80 | ~100B | set 后永不淘汰 |

场景：6 实例 × 230 题 × 每题 3-5 workspace = 数千 workspace → 数千个 SQLite handle + 数万 session/run ID 条目。

**这些 Map 都有安全回退路径**，淘汰后功能不受影响：
- `#sessionIndex`/`#runIndex` miss → `lookupWorkspaceIdInRegistry()`（registry DB）→ 全库扫描
- `#handles` miss → `ensureHandle()` 重新打开 SQLite 文件
- `#workspaceRecords` miss → `loadWorkspaceRecordFromRegistry()` 从 registry DB 重载

## 修改方案：给 4 个 Map 加 LRU 淘汰 + workspace pinning 防并发竞态

### 修改文件清单

| 文件 | 改动 |
|------|------|
| `packages/storage-sqlite/src/bounded-lru-map.ts` | **新建**：通用 LRU Map 实现 |
| `packages/storage-sqlite/src/coordinator.ts` | 核心改动：4 个 Map 换 BoundedLRUMap + 新增 eviction 配置 + pin/unpin + loadWorkspaceRecordFromRegistry + 4 个全扫描方法改用 listPersistedWorkspaces |
| `packages/storage-sqlite/src/index.ts` | 透传 eviction 配置 |
| `packages/config/src/types.ts` | 配置类型增加 eviction 字段 |
| `apps/server/src/bootstrap.ts` | 读取 eviction 配置并透传 |
| `test_oah_server2/oah_instance_*/daemon.yaml` × 6 | 添加 eviction 配置 |

### Step 1：新建 `packages/storage-sqlite/src/bounded-lru-map.ts`

通用 LRU Map，替代原生 `Map`：

```typescript
export interface BoundedLRUMapOptions<K, V> {
  maxSize: number;                    // Infinity = 不淘汰（向后兼容）
  canEvict?: (key: K) => boolean;     // 返回 false 则跳过，找下一个
  onEvict?: (key: K, value: V) => void; // 淘汰时回调
}

export class BoundedLRUMap<K, V> {
  // 内部：Map<K, { value: V; prev: K | null; next: K | null }> + 双向链表
  // head = 最近访问，tail = 最久未用

  get size(): number;
  get(key: K): V | undefined;          // 命中时提升到 head
  set(key: K, value: V): this;         // 插入/更新到 head，超容量则从 tail 淘汰
  has(key: K): boolean;                // 不提升
  delete(key: K): boolean;             // 从链表和 Map 中移除
  clear(): void;
  entries(): IterableIterator<[K, V]>; // head→tail 顺序
  values(): IterableIterator<V>;
  keys(): IterableIterator<K>;
  forEach(cb: (v: V, k: K) => void): void;
  get tailKey(): K | undefined;        // 暴露最久未用的 key
}
```

淘汰逻辑（在 `set` 中触发）：
1. 从 tail 开始扫描
2. 对每个候选 key 调用 `canEvict(key)` → 若 false 则跳过找下一个
3. 找到可淘汰项 → 从 Map 和链表中移除 → 调用 `onEvict(key, value)`
4. 若无可淘汰项 → 暂时超过 maxSize（所有项都在活跃使用）
5. `maxSize = Infinity` → 永不触发淘汰

### Step 2：修改 `coordinator.ts`

#### 2a. 新增配置类型

```typescript
export interface CoordinatorEvictionOptions {
  maxWorkspaceRecords?: number;    // 默认 Infinity
  maxOpenHandles?: number;         // 默认 Infinity
  maxSessionIndexEntries?: number; // 默认 Infinity
  maxRunIndexEntries?: number;     // 默认 Infinity
}
```

#### 2b. 构造函数改造

```typescript
export class SQLitePersistenceCoordinator {
  readonly #shadowRoot: string;
  readonly #projectDbLocation: "shadow" | "workspace";
  readonly #registryDbPath: string;
  readonly #evictionOptions: CoordinatorEvictionOptions;
  readonly #workspaceRecords: BoundedLRUMap<string, WorkspaceRecord>;
  readonly #handles: BoundedLRUMap<string, DatabaseHandle>;
  readonly #sessionIndex: BoundedLRUMap<string, string>;
  readonly #runIndex: BoundedLRUMap<string, string>;
  readonly #activeWorkspaceRefs = new Map<string, number>();  // 引用计数
  #registryDb: DatabaseSync | undefined;

  constructor(shadowRoot: string, options: {
    projectDbLocation?: "shadow" | "workspace" | undefined;
    eviction?: CoordinatorEvictionOptions | undefined;
  } = {}) {
    this.#shadowRoot = shadowRoot;
    this.#projectDbLocation = options.projectDbLocation ?? "workspace";
    this.#registryDbPath = path.join(shadowRoot, "workspace-registry.db");
    this.#evictionOptions = options.eviction ?? {};

    const isPinned = (key: string) => this.#activeWorkspaceRefs.has(key);

    // handles: 淘汰时关闭 SQLite 连接；不能淘汰正在使用的 workspace
    this.#handles = new BoundedLRUMap<string, DatabaseHandle>({
      maxSize: this.#evictionOptions.maxOpenHandles ?? Infinity,
      canEvict: isPinned,
      onEvict: (_key, handle) => { handle.db.close(); }
    });

    // workspaceRecords: 淘汰时级联关闭 handle + 删除 indexes
    this.#workspaceRecords = new BoundedLRUMap<string, WorkspaceRecord>({
      maxSize: this.#evictionOptions.maxWorkspaceRecords ?? Infinity,
      canEvict: isPinned,
      onEvict: (workspaceId) => {
        const handle = this.#handles.get(workspaceId);
        if (handle) { handle.db.close(); this.#handles.delete(workspaceId); }
        this.deleteWorkspaceIndexes(workspaceId);
      }
    });

    // sessionIndex / runIndex: 纯缓存，淘汰无副作用
    this.#sessionIndex = new BoundedLRUMap<string, string>({
      maxSize: this.#evictionOptions.maxSessionIndexEntries ?? Infinity,
    });
    this.#runIndex = new BoundedLRUMap<string, string>({
      maxSize: this.#evictionOptions.maxRunIndexEntries ?? Infinity,
    });
  }
```

#### 2c. 新增 pin/unpin 方法

```typescript
pinWorkspace(workspaceId: string): void {
  const count = this.#activeWorkspaceRefs.get(workspaceId) ?? 0;
  this.#activeWorkspaceRefs.set(workspaceId, count + 1);
}

unpinWorkspace(workspaceId: string): void {
  const count = this.#activeWorkspaceRefs.get(workspaceId);
  if (count !== undefined && count > 1) {
    this.#activeWorkspaceRefs.set(workspaceId, count - 1);
  } else {
    this.#activeWorkspaceRefs.delete(workspaceId);
  }
}
```

#### 2d. 新增 `loadWorkspaceRecordFromRegistry()`

当 `#workspaceRecords` miss 时从 registry DB 重载：

```typescript
async loadWorkspaceRecordFromRegistry(workspaceId: string): Promise<WorkspaceRecord | undefined> {
  const registryDb = await this.ensureRegistryDb();
  const row = registryDb
    .prepare("select payload from workspace_registry where id = ? limit 1")
    .get(workspaceId) as JsonRow | undefined;
  if (!row?.payload) return undefined;
  return JSON.parse(row.payload) as WorkspaceRecord;
}
```

#### 2e. 修改 `getWorkspaceHandle()`（当前第 184-191 行）

缓存 miss 时先从 registry DB 加载，再抛异常：

```typescript
async getWorkspaceHandle(workspaceId: string): Promise<DatabaseHandle> {
  let workspace = this.#workspaceRecords.get(workspaceId);
  if (!workspace) {
    workspace = await this.loadWorkspaceRecordFromRegistry(workspaceId);
    if (workspace) {
      this.#workspaceRecords.set(workspaceId, workspace);
    }
  }
  if (!workspace) {
    throw new AppError(404, "workspace_not_found", `Workspace ${workspaceId} was not found.`);
  }
  this.pinWorkspace(workspaceId);
  try {
    return await this.ensureHandle(workspace);
  } finally {
    this.unpinWorkspace(workspaceId);
  }
}
```

**注意**：`pinWorkspace` 在 `ensureHandle` 之前调用，`unpinWorkspace` 在之后调用。这确保 `ensureHandle` 期间的 `set` 操作不会因 LRU 淘汰掉当前 workspace 的 handle。

#### 2f. 修改 4 个全库扫描方法

`getWorkspaceIdForSession`、`getWorkspaceIdForRun`、`getWorkspaceIdForMessage`、`getWorkspaceIdForSessionEvent` 中的 fallback 全扫描循环，将 `this.#workspaceRecords.values()` 改为 `await this.listPersistedWorkspaces()`：

```typescript
// 之前（第 205-214 行）：
for (const workspace of this.#workspaceRecords.values()) {
  const handle = await this.ensureHandle(workspace);
  ...

// 之后：
for (const workspace of await this.listPersistedWorkspaces()) {
  this.#workspaceRecords.set(workspace.id, workspace);  // re-cache
  const handle = await this.ensureHandle(workspace);
  ...
```

4 个方法全部按此模式修改。

#### 2g. 修改 `reindexWorkspace()`（当前第 351-427 行）

此方法批量 `set` 大量 session/run index 条目。每个 `set` 可能触发 LRU 淘汰，这是预期行为。但需要注意 `#sessionIndex` 和 `#runIndex` 的淘汰无副作用，安全。

唯一风险：reindex 期间淘汰了当前 workspace 自身的其他 workspace 的 index 条目——这是安全的，因为被淘汰的是 least recently used，且回退路径存在。

无需特殊修改，`BoundedLRUMap.set` 自动处理。

#### 2h. 确认 `deleteWorkspace()` 无需修改

当前 `deleteWorkspace()` 已经正确地：
1. 从 `#workspaceRecords` 删除
2. 调用 `deleteWorkspaceIndexes()` 清理 `#sessionIndex` 和 `#runIndex`
3. 关闭并从 `#handles` 删除

使用 `BoundedLRUMap` 后，`delete` 方法从链表和 Map 中移除条目，行为一致。无需修改。

### Step 3：修改 `packages/storage-sqlite/src/index.ts`

```typescript
export interface CreateSQLiteRuntimePersistenceOptions {
  shadowRoot: string;
  projectDbLocation?: "shadow" | "workspace" | undefined;
  eviction?: CoordinatorEvictionOptions | undefined;  // 新增
}

export async function createSQLiteRuntimePersistence(options: CreateSQLiteRuntimePersistenceOptions) {
  const coordinator = new SQLitePersistenceCoordinator(options.shadowRoot, {
    projectDbLocation: options.projectDbLocation,
    eviction: options.eviction  // 透传
  });
  // ... 其余不变
}
```

### Step 4：修改 `packages/config/src/types.ts`

当前（第 19-23 行）：
```typescript
sqlite?: {
  project_db_location?: "shadow" | "workspace" | undefined;
} | undefined;
```

改为：
```typescript
sqlite?: {
  project_db_location?: "shadow" | "workspace" | undefined;
  eviction?: {
    max_workspace_records?: number | undefined;
    max_open_handles?: number | undefined;
    max_session_index_entries?: number | undefined;
    max_run_index_entries?: number | undefined;
  } | undefined;
} | undefined;
```

### Step 5：修改 `apps/server/src/bootstrap.ts`（第 1323-1326 行附近）

```typescript
// 当前：
await sqliteStorageModule!.createSQLiteRuntimePersistence({
  shadowRoot: sqliteShadowRoot,
  projectDbLocation: config.storage.sqlite?.project_db_location
});

// 改为：
const evictionConfig = config.storage.sqlite?.eviction;
await sqliteStorageModule!.createSQLiteRuntimePersistence({
  shadowRoot: sqliteShadowRoot,
  projectDbLocation: config.storage.sqlite?.project_db_location,
  eviction: evictionConfig ? {
    maxWorkspaceRecords: evictionConfig.max_workspace_records,
    maxOpenHandles: evictionConfig.max_open_handles,
    maxSessionIndexEntries: evictionConfig.max_session_index_entries,
    maxRunIndexEntries: evictionConfig.max_run_index_entries,
  } : undefined
});
```

### Step 6：修改 6 个 daemon.yaml

每个 `test_oah_server2/oah_instance_*/daemon.yaml` 添加 eviction 配置：

```yaml
storage:
  sqlite:
    project_db_location: shadow
    eviction:
      max_workspace_records: 200
      max_open_handles: 100
      max_session_index_entries: 1000
      max_run_index_entries: 2000
```

## 向后兼容性

- 所有 `eviction` 字段可选，默认 `Infinity`（不淘汰）
- `BoundedLRUMap` 在 `maxSize = Infinity` 时行为与原生 `Map` 一致
- 未配置 eviction 的现有部署无需任何改动

## 竞态安全性分析

| 竞态场景 | 分析 | 结论 |
|---------|------|------|
| 淘汰正在使用的 handle | `canEvict` 检查 `#activeWorkspaceRefs`，pin 的 workspace 不会被淘汰 | 安全 |
| `getWorkspaceHandle` 返回后、使用前 handle 被淘汰 | `get` 调用将条目提升到 head（最近使用），LRU 淘汰从 tail（最久未用），不会淘汰刚 get 的条目 | 安全 |
| reindex 批量 set 触发淘汰 | 淘汰的是其他 workspace 的 least-recent 条目，当前 workspace 刚 set 到 head | 安全 |
| 全扫描方法重载 registry 后重新 set | 新 set 的条目到 head，不会立即被淘汰 | 安全 |

## 验证方法

1. **编译**：`cd oah && pnpm build` 无报错
2. **启动**：用修改后的 daemon.yaml 启动 OAH 实例，确认正常监听
3. **单题功能**：跑 1 个 benchmark 题，确认 create workspace → create session → send message → wait for run → delete workspace 全链路正常
4. **淘汰回退**：设 `max_open_handles: 3`，跑 10 题，确认被淘汰的 workspace 通过 registry DB 回退正确
5. **内存验证**：跑 50+ 题，观察进程 RSS 不再持续增长
6. **压测**：跑完整 230 题确认不崩溃
