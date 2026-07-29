// Checks the "nbdsl_document" comm payload built from a notebook's cell models.
// Run with `jlpm test` (compiles src/documentMessage.ts to .test-build/ first).
const assert = require('assert');
const { buildDocumentMessage } = require('../.test-build/documentMessage.js');

const cell = (type, id, source) => ({
  type,
  id,
  sharedModel: { getSource: () => source }
});

assert.deepStrictEqual(
  buildDocumentMessage([
    cell('code', 'a', 'def f := 1'),
    cell('markdown', 'b', '# heading'),
    cell('code', 'c', ''),
    cell('raw', 'd', 'raw'),
    cell('code', 'e', 'line1\nline2')
  ]),
  {
    type: 'document',
    cells: [
      { id: 'a', source: 'def f := 1' },
      { id: 'c', source: '' },
      { id: 'e', source: 'line1\nline2' }
    ]
  }
);

// Order is the notebook's order, not sorted or deduped by anything.
assert.deepStrictEqual(
  buildDocumentMessage([cell('code', 'z', '2'), cell('code', 'y', '1')]).cells,
  [
    { id: 'z', source: '2' },
    { id: 'y', source: '1' }
  ]
);

assert.deepStrictEqual(buildDocumentMessage([]), {
  type: 'document',
  cells: []
});

console.log('document: all checks passed');
