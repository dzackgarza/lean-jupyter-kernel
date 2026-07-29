import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { IEditorLanguageRegistry } from '@jupyterlab/codemirror';
import { ISettingRegistry } from '@jupyterlab/settingregistry';
import { LanguageSupport, StreamLanguage } from '@codemirror/language';
import { makeLean4Parser } from './lean4';
import documentPlugin from './document';
import pathRendererPlugin from './pathRenderer';

const LANGUAGE_ID = 'jupyterlab_nbdsl:language';

// Mirrors schema/language.json's default, for the settings-unavailable path.
const DEFAULT_DSL_KEYWORDS = ['prefer'];

function readKeywords(settings: ISettingRegistry.ISettings): string[] {
  const value = settings.composite.dslKeywords;
  return Array.isArray(value) && value.every(k => typeof k === 'string')
    ? (value as string[])
    : DEFAULT_DSL_KEYWORDS;
}

const languagePlugin: JupyterFrontEndPlugin<void> = {
  id: LANGUAGE_ID,
  description: 'Lean 4 syntax highlighting for nbdsl notebook cells',
  autoStart: true,
  requires: [IEditorLanguageRegistry, ISettingRegistry],
  activate: (
    _app: JupyterFrontEnd,
    languages: IEditorLanguageRegistry,
    settings: ISettingRegistry
  ) => {
    // ponytail: registered once at startup; changing dslKeywords needs a
    // reload, since re-registering would not retarget already-open editors.
    const register = (extra: string[]): void => {
      languages.addLanguage({
        name: 'lean4',
        displayName: 'Lean 4',
        mime: 'text/x-lean4',
        extensions: ['lean'],
        support: new LanguageSupport(
          StreamLanguage.define(makeLean4Parser(extra))
        )
      });
    };

    void settings.load(LANGUAGE_ID).then(
      loaded => register(readKeywords(loaded)),
      () => register(DEFAULT_DSL_KEYWORDS)
    );
  }
};

export default [languagePlugin, documentPlugin, pathRendererPlugin];
