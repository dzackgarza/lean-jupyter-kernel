import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { IEditorLanguageRegistry } from '@jupyterlab/codemirror';
import { LanguageSupport, StreamLanguage } from '@codemirror/language';
import { leanParser } from './lean4';
import documentPlugin from './document';

const languagePlugin: JupyterFrontEndPlugin<void> = {
  id: 'jupyterlab_nbdsl:language',
  description: 'Lean 4 syntax highlighting for nbdsl notebook cells',
  autoStart: true,
  requires: [IEditorLanguageRegistry],
  activate: (_app: JupyterFrontEnd, languages: IEditorLanguageRegistry) => {
    languages.addLanguage({
      name: 'lean4',
      displayName: 'Lean 4',
      mime: 'text/x-lean4',
      extensions: ['lean'],
      support: new LanguageSupport(StreamLanguage.define(leanParser))
    });
  }
};

export default [languagePlugin, documentPlugin];
