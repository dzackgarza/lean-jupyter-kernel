import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { IRenderMimeRegistry } from '@jupyterlab/rendermime';
import { IRenderMime } from '@jupyterlab/rendermime-interfaces';
import { Widget } from '@lumino/widgets';
import { buildFallbackNode, buildPathNode, parsePath, PATH_MIME_TYPE } from './pathData';

// Beats the built-in text/plain factory (defaultRank 120) so the chain wins
// over the text/plain fallback the kernel always ships alongside it.
const RANK = 10;

class PathWidget extends Widget implements IRenderMime.IRenderer {
  constructor(private _mimeType: string) {
    super();
    this.addClass('nbdsl-path-widget');
  }

  renderModel(model: IRenderMime.IMimeModel): Promise<void> {
    const data = model.data[this._mimeType];
    this.node.textContent = '';
    let child: HTMLElement;
    try {
      const path = parsePath(data);
      child = path ? buildPathNode(path) : buildFallbackNode(data);
    } catch {
      child = buildFallbackNode(data);
    }
    this.node.appendChild(child);
    return Promise.resolve();
  }
}

export const pathRendererFactory: IRenderMime.IRendererFactory = {
  safe: true,
  mimeTypes: [PATH_MIME_TYPE],
  defaultRank: RANK,
  createRenderer: options => new PathWidget(options.mimeType)
};

const plugin: JupyterFrontEndPlugin<void> = {
  id: 'jupyterlab_nbdsl:path-renderer',
  description: 'Renders nbdsl transport paths as a functor chain',
  autoStart: true,
  requires: [IRenderMimeRegistry],
  activate: (_app: JupyterFrontEnd, rendermime: IRenderMimeRegistry) => {
    rendermime.addFactory(pathRendererFactory, RANK);
  }
};

export default plugin;
