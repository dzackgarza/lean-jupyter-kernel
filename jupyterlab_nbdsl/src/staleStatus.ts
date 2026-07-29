// Pure handling of the kernel's "status" comm message, kept free of any
// JupyterLab imports so `jlpm test` can compile and exercise it under plain node.

export const STALE_CLASS = 'nbdsl-stale';

/** `{"type": "status", "fresh": [...], "stale": [...]}` sent on the document comm. */
export interface StatusMessage {
  type: 'status';
  fresh: string[];
  stale: string[];
}

export function isStatusMessage(data: unknown): data is StatusMessage {
  const msg = data as Partial<StatusMessage> | null;
  return (
    !!msg &&
    msg.type === 'status' &&
    Array.isArray(msg.fresh) &&
    Array.isArray(msg.stale)
  );
}

/**
 * Split `cellIds` by the message's `stale` list. `fresh` is deliberately not
 * consulted: each message carries complete lists, so every cell that is not
 * stale — fresh or never run — must lose the class.
 */
export function computeStaleClassUpdates(
  ids: { stale: string[] },
  cellIds: string[]
): { addStale: string[]; removeStale: string[] } {
  const stale = new Set(ids.stale);
  const addStale: string[] = [];
  const removeStale: string[] = [];
  for (const id of cellIds) {
    (stale.has(id) ? addStale : removeStale).push(id);
  }
  return { addStale, removeStale };
}
