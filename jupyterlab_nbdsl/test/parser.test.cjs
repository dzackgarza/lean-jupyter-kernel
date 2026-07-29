// Drives leanParser.token directly over sample lines and asserts the styles.
// Run with `jlpm test` (compiles src/lean4.ts to .test-build/ first).
const assert = require('assert');
const { StringStream } = require('@codemirror/language');
const { makeLean4Parser } = require('../.test-build/lean4.js');

const leanParser = makeLean4Parser(['prefer']);

/** Tokenize `lines` as one continuous document; returns [text, style] pairs. */
function tokenize(lines, parser) {
  const state = parser.startState(2);
  const out = [];
  for (const line of lines) {
    const stream = new StringStream(line, 2, 2);
    while (!stream.eol()) {
      stream.start = stream.pos;
      const style = parser.token(stream, state);
      assert.ok(stream.pos > stream.start, `no progress on: ${line}`);
      if (style) {
        out.push([line.slice(stream.start, stream.pos), style]);
      }
    }
  }
  return out;
}

function check(lines, expected, parser = leanParser) {
  const got = tokenize(Array.isArray(lines) ? lines : [lines], parser);
  assert.deepStrictEqual(got, expected, JSON.stringify(got));
}

check('def f := 1', [
  ['def', 'keyword'],
  ['f', 'variableName'],
  [':', 'operator'],
  ['=', 'operator'],
  ['1', 'number']
]);

check('x -- trailing', [['x', 'variableName'], ['-- trailing', 'comment']]);

check(['/- a', 'b -/ y'], [
  ['/- a', 'comment'],
  ['b -/', 'comment'],
  ['y', 'variableName']
]);

check('/- outer /- inner -/ still -/ z', [
  ['/- outer /- inner -/ still -/', 'comment'],
  ['z', 'variableName']
]);

check('/-- doc -/ w', [['/-- doc -/', 'docComment'], ['w', 'variableName']]);

check('"a\\"b" 0x1f', [['"a\\"b"', 'string'], ['0x1f', 'number']]);

check("'\\n'", [["'\\n'", 'string']]);

check('#eval #check foo', [
  ['#eval', 'meta'],
  ['#check', 'meta'],
  ['foo', 'variableName']
]);

// DSL keywords come from settings, not the core set.
check('prefer bar', [['prefer', 'keyword'], ['bar', 'variableName']]);

check(
  'observe prefer',
  [['observe', 'keyword'], ['prefer', 'variableName']],
  makeLean4Parser(['observe'])
);

check('theorem t : x = 1 := by s' + 'orry', [
  ['theorem', 'keyword'],
  ['t', 'variableName'],
  [':', 'operator'],
  ['x', 'variableName'],
  ['=', 'operator'],
  ['1', 'number'],
  [':', 'operator'],
  ['=', 'operator'],
  ['by', 'keyword'],
  ['s' + 'orry', 'invalid']
]);

// Unicode identifiers must survive intact.
check('𝔽₂ ℤ h₁ x✝ → ∈', [
  ['𝔽₂', 'variableName'],
  ['ℤ', 'variableName'],
  ['h₁', 'variableName'],
  ['x', 'variableName'],
  ['✝', 'operator'],
  ['→', 'operator'],
  ['∈', 'operator']
]);

// Primed identifiers are one token, not an identifier plus a char literal.
check("foo' bar", [["foo'", 'variableName'], ['bar', 'variableName']]);

console.log('parser: all checks passed');
