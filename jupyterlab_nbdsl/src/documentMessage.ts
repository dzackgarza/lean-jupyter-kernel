// Pure message construction for the "nbdsl_document" comm, kept free of any
// JupyterLab imports so `jlpm test` can compile and exercise it under plain node.

/** Structural subset of `@jupyterlab/cells`' ICellModel that we read. */
export interface IDocumentCell {
  readonly type: string;
  readonly id: string;
  readonly sharedModel: { getSource(): string };
}

export type DocumentMessage = {
  type: 'document';
  cells: { id: string; source: string }[];
};

/** Full current order of *code* cells; markdown and raw cells are skipped. */
export function buildDocumentMessage(
  cells: Iterable<IDocumentCell>
): DocumentMessage {
  const out: DocumentMessage['cells'] = [];
  for (const cell of cells) {
    if (cell.type === 'code') {
      out.push({ id: cell.id, source: cell.sharedModel.getSource() });
    }
  }
  return { type: 'document', cells: out };
}
