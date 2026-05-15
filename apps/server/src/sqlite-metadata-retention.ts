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

const DEFAULT_INTERVAL_MS = 60 * 60 * 1000;
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
    if (this.#timer) {
      return;
    }

    this.#timer = setInterval(() => {
      void this.runOnce().catch((error: unknown) => {
        this.#logger.warn?.("SQLite metadata retention failed.", error);
      });
    }, this.#intervalMs);
    this.#timer.unref?.();

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

      const terminalRuns = await this.#coordinator.listTerminalRunIds(cutoff, this.#batchLimit);
      summary.workspacesScanned = new Set(terminalRuns.map(r => r.workspaceId)).size;

      if (terminalRuns.length > 0) {
        const runIds = terminalRuns.map(r => r.runId);
        summary.deltasDeleted = await this.#sessionEventStore.deleteDeltasByRunIds(runIds);

        this.#runCount++;
        if (this.#runCount % this.#vacuumIntervalRuns === 0 && summary.deltasDeleted > 0) {
          const workspaceIds = [...new Set(terminalRuns.map(r => r.workspaceId))];
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
