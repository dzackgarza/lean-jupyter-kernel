// Checks the stale/fresh split driving the `nbdsl-stale` cell class.
// Run with `jlpm test` (compiles src/staleStatus.ts to .test-build/ first).
const assert = require('assert');
const {
  computeStaleClassUpdates,
  isStatusMessage
} = require('../.test-build/staleStatus.js');

// Cells not named at all (never run) are removals, same as fresh ones.
assert.deepStrictEqual(
  computeStaleClassUpdates({ fresh: ['a'], stale: ['b', 'd'] }, [
    'a',
    'b',
    'c',
    'd'
  ]),
  { addStale: ['b', 'd'], removeStale: ['a', 'c'] }
);

// Ids the kernel reports but the notebook no longer has are simply dropped.
assert.deepStrictEqual(
  computeStaleClassUpdates({ fresh: [], stale: ['gone'] }, ['a']),
  { addStale: [], removeStale: ['a'] }
);

assert.deepStrictEqual(computeStaleClassUpdates({ fresh: [], stale: [] }, []), {
  addStale: [],
  removeStale: []
});

assert.ok(isStatusMessage({ type: 'status', fresh: [], stale: [] }));
assert.ok(!isStatusMessage({ type: 'document', cells: [] }));
assert.ok(!isStatusMessage({ type: 'status', stale: [] }));
assert.ok(!isStatusMessage(null));
assert.ok(!isStatusMessage('status'));

console.log('stale: all checks passed');
