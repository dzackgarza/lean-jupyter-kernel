// Validation of the application/vnd.nbdsl.path+json payload. The DOM builders
// need a document, so only the parse gate is exercised here.
const assert = require('assert');
const { parsePath, PATH_MIME_TYPE } = require('../.test-build/pathData.js');

assert.strictEqual(PATH_MIME_TYPE, 'application/vnd.nbdsl.path+json');

const good = {
  object: 'G',
  source: 'NbDsl.Std.Groups',
  target: 'NbDsl.Std.Sets',
  steps: ['NbDsl.Std.groupsToSets']
};
assert.deepStrictEqual(parsePath(good), good);

// Zero steps is still well-formed.
assert.ok(parsePath({ ...good, steps: [] }));

// Anything malformed must be rejected so the renderer can fall back.
for (const bad of [
  null,
  undefined,
  'a string',
  42,
  [],
  { ...good, object: undefined },
  { ...good, source: 3 },
  { ...good, target: null },
  { ...good, steps: 'NbDsl.Std.groupsToSets' },
  { ...good, steps: ['ok', 7] }
]) {
  assert.strictEqual(parsePath(bad), null, `accepted: ${JSON.stringify(bad)}`);
}

console.log('path: all checks passed');
