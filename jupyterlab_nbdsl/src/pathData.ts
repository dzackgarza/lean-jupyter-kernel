// Pure data + DOM construction for the nbdsl path MIME type. No JupyterLab
// imports, so `jlpm test` can compile and require this directly.

export const PATH_MIME_TYPE = 'application/vnd.nbdsl.path+json';

export interface IPathData {
  /** The object being transported, e.g. "G". */
  object: string;
  /** Fully-qualified source namespace. */
  source: string;
  /** Fully-qualified target namespace. */
  target: string;
  /** Registered functor names applied in order, source to target. */
  steps: string[];
}

function isStringArray(v: unknown): v is string[] {
  return Array.isArray(v) && v.every(s => typeof s === 'string');
}

/** Validate a MIME payload; null when it is not a well-formed path. */
export function parsePath(data: unknown): IPathData | null {
  if (!data || typeof data !== 'object') {
    return null;
  }
  const d = data as Record<string, unknown>;
  if (
    typeof d.object !== 'string' ||
    typeof d.source !== 'string' ||
    typeof d.target !== 'string' ||
    !isStringArray(d.steps)
  ) {
    return null;
  }
  return d as unknown as IPathData;
}

/** Last dotted component; the whole name when there is no dot. */
function shortName(name: string): string {
  return name.slice(name.lastIndexOf('.') + 1) || name;
}

function labelled(cls: string, full: string): HTMLElement {
  const el = document.createElement('span');
  el.className = cls;
  el.textContent = shortName(full);
  el.title = full;
  return el;
}

function arrow(step?: string): HTMLElement {
  const el = document.createElement('span');
  el.className = 'nbdsl-path-arrow';
  if (step !== undefined) {
    el.appendChild(labelled('nbdsl-path-step', step));
  }
  const glyph = document.createElement('span');
  glyph.className = 'nbdsl-path-glyph';
  glyph.textContent = '→';
  el.appendChild(glyph);
  return el;
}

export function buildPathNode(path: IPathData): HTMLElement {
  const root = document.createElement('div');
  root.className = 'nbdsl-path';
  root.appendChild(labelled('nbdsl-path-object', path.object));

  const chain = document.createElement('div');
  chain.className = 'nbdsl-path-chain';
  chain.appendChild(labelled('nbdsl-path-node', path.source));

  if (path.steps.length === 0) {
    chain.appendChild(arrow());
  } else {
    path.steps.forEach((step, i) => {
      chain.appendChild(arrow(step));
      if (i < path.steps.length - 1) {
        // The payload names only the endpoints, so objects between successive
        // functors are shown as anonymous waypoints rather than invented.
        const dot = document.createElement('span');
        dot.className = 'nbdsl-path-node nbdsl-path-waypoint';
        dot.textContent = '·';
        chain.appendChild(dot);
      }
    });
  }

  chain.appendChild(labelled('nbdsl-path-node', path.target));
  root.appendChild(chain);
  return root;
}

/** Last-resort rendering for payloads that are not a valid path. */
export function buildFallbackNode(data: unknown): HTMLElement {
  const pre = document.createElement('pre');
  pre.className = 'nbdsl-path-fallback';
  try {
    pre.textContent = JSON.stringify(data, null, 2) ?? String(data);
  } catch {
    pre.textContent = String(data);
  }
  return pre;
}
