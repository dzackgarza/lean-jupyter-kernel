import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import {
  INotebookTracker,
  NotebookActions,
  NotebookPanel
} from '@jupyterlab/notebook';
import { Kernel } from '@jupyterlab/services';
import { buildDocumentMessage } from './documentMessage';
import {
  computeStaleClassUpdates,
  isStatusMessage,
  STALE_CLASS
} from './staleStatus';

const COMM_TARGET = 'nbdsl_document';
const DEBOUNCE_MS = 100;

// Sends are per-panel, so `executionScheduled` needs a way back from the
// notebook to its sender.
const senders = new WeakMap<NotebookPanel, () => void>();

/** Mark the cells the kernel reports stale; unmark every other cell. */
function applyStatus(panel: NotebookPanel, data: unknown): void {
  if (!isStatusMessage(data)) {
    return;
  }
  const byId = new Map(panel.content.widgets.map(w => [w.model.id, w] as const));
  const { addStale, removeStale } = computeStaleClassUpdates(data, [
    ...byId.keys()
  ]);
  for (const id of addStale) {
    byId.get(id)?.node.classList.add(STALE_CLASS);
  }
  for (const id of removeStale) {
    byId.get(id)?.node.classList.remove(STALE_CLASS);
  }
}

function track(panel: NotebookPanel): void {
  let comm: Kernel.IComm | null = null;
  let timer = 0;
  let restarting = false;

  const send = (): void => {
    const model = panel.content.model;
    const kernel = panel.sessionContext.session?.kernel;
    if (!model || !kernel) {
      return;
    }
    if (comm?.isDisposed) {
      comm = null;
    }
    if (!comm) {
      comm = kernel.createComm(COMM_TARGET);
      comm.onMsg = msg => applyStatus(panel, msg.content.data);
      comm.open({});
    }
    comm.send(buildDocumentMessage(model.cells));
  };

  const sendDebounced = (): void => {
    window.clearTimeout(timer);
    timer = window.setTimeout(send, DEBOUNCE_MS);
  };

  const sendNow = (): void => {
    window.clearTimeout(timer);
    send();
  };
  senders.set(panel, sendNow);

  panel.sessionContext.kernelChanged.connect(() => {
    comm = null;
    sendNow();
  });

  // A restart keeps the same kernel connection but drops the kernel-side comm,
  // so rebuild it and resend once the kernel is back.
  panel.sessionContext.statusChanged.connect((_, status) => {
    if (status === 'restarting' || status === 'autorestarting') {
      comm = null;
      restarting = true;
    } else if (restarting && status === 'idle') {
      restarting = false;
      sendNow();
    }
  });

  void panel.context.ready.then(() => {
    // sharedModel.changed covers cell text edits AND list operations
    // (add/remove/move) — cells.changed alone misses typing, so staleness
    // would only update at execution time.
    panel.content.model?.sharedModel.changed.connect(sendDebounced);
    sendNow();
  });

  panel.disposed.connect(() => {
    window.clearTimeout(timer);
    comm = null;
  });
}

const plugin: JupyterFrontEndPlugin<void> = {
  id: 'jupyterlab_nbdsl:document',
  description: 'Streams notebook code-cell order and sources to the kernel',
  autoStart: true,
  requires: [INotebookTracker],
  activate: (_app: JupyterFrontEnd, tracker: INotebookTracker) => {
    tracker.widgetAdded.connect((_, panel) => track(panel));

    // `executionScheduled` fires before the execute_request is dispatched, so
    // this comm_msg reaches the shell channel first and the kernel has fresh
    // sources by the time it handles the execution. That ordering is the whole
    // point of hooking this signal rather than `executed`.
    NotebookActions.executionScheduled.connect((_, args) => {
      const panel = tracker.find(p => p.content === args.notebook);
      if (panel) {
        senders.get(panel)?.();
      }
    });
  }
};

export default plugin;
