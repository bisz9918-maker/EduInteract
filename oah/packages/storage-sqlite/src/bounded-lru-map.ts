export interface BoundedLRUMapOptions<K, V> {
  maxSize: number;
  canEvict?: (key: K) => boolean;
  onEvict?: (key: K, value: V) => void;
}

interface ListNode<K, V> {
  value: V;
  prev: K | null;
  next: K | null;
}

export class BoundedLRUMap<K, V> {
  readonly #map = new Map<K, ListNode<K, V>>();
  readonly #maxSize: number;
  readonly #canEvict: ((key: K) => boolean) | undefined;
  readonly #onEvict: ((key: K, value: V) => void) | undefined;
  #head: K | null = null;
  #tail: K | null = null;

  constructor(options: BoundedLRUMapOptions<K, V>) {
    this.#maxSize = options.maxSize;
    this.#canEvict = options.canEvict;
    this.#onEvict = options.onEvict;
  }

  get size(): number {
    return this.#map.size;
  }

  get(key: K): V | undefined {
    const node = this.#map.get(key);
    if (!node) return undefined;
    this.#moveToHead(key, node);
    return node.value;
  }

  set(key: K, value: V): this {
    const existing = this.#map.get(key);
    if (existing) {
      existing.value = value;
      this.#moveToHead(key, existing);
    } else {
      this.#map.set(key, { value, prev: null, next: this.#head });
      if (this.#head !== null) {
        const headNode = this.#map.get(this.#head);
        if (headNode) headNode.prev = key;
      }
      this.#head = key;
      if (this.#tail === null) {
        this.#tail = key;
      }
      this.#evictIfNeeded();
    }
    return this;
  }

  has(key: K): boolean {
    return this.#map.has(key);
  }

  delete(key: K): boolean {
    const node = this.#map.get(key);
    if (!node) return false;
    this.#removeNode(key, node);
    this.#map.delete(key);
    return true;
  }

  clear(): void {
    this.#map.clear();
    this.#head = null;
    this.#tail = null;
  }

  *entries(): IterableIterator<[K, V]> {
    let current = this.#head;
    while (current !== null) {
      const node = this.#map.get(current)!;
      yield [current, node.value];
      current = node.next;
    }
  }

  *values(): IterableIterator<V> {
    for (const [, value] of this.entries()) {
      yield value;
    }
  }

  *keys(): IterableIterator<K> {
    for (const [key] of this.entries()) {
      yield key;
    }
  }

  forEach(cb: (v: V, k: K) => void): void {
    for (const [k, v] of this.entries()) {
      cb(v, k);
    }
  }

  get tailKey(): K | undefined {
    return this.#tail ?? undefined;
  }

  #moveToHead(key: K, node: ListNode<K, V>): void {
    if (this.#head === key) return;
    this.#removeNode(key, node);
    node.prev = null;
    node.next = this.#head;
    if (this.#head !== null) {
      const headNode = this.#map.get(this.#head);
      if (headNode) headNode.prev = key;
    }
    this.#head = key;
  }

  #removeNode(key: K, node: ListNode<K, V>): void {
    if (node.prev !== null) {
      const prevNode = this.#map.get(node.prev);
      if (prevNode) prevNode.next = node.next;
    } else {
      this.#head = node.next;
    }
    if (node.next !== null) {
      const nextNode = this.#map.get(node.next);
      if (nextNode) nextNode.prev = node.prev;
    } else {
      this.#tail = node.prev;
    }
    node.prev = null;
    node.next = null;
  }

  #evictIfNeeded(): void {
    if (this.#maxSize === Infinity || this.#maxSize <= 0) return;
    while (this.#map.size > this.#maxSize) {
      const evicted = this.#evictOne();
      if (!evicted) break;
    }
  }

  #evictOne(): boolean {
    let candidate: K | null = this.#tail;
    while (candidate !== null) {
      if (this.#canEvict && !this.#canEvict(candidate)) {
        const node = this.#map.get(candidate);
        candidate = node?.prev ?? null;
        continue;
      }
      const node = this.#map.get(candidate)!;
      this.#onEvict?.(candidate, node.value);
      this.#removeNode(candidate, node);
      this.#map.delete(candidate);
      return true;
    }
    return false;
  }
}
