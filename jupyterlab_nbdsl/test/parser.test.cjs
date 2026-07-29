// Drives leanParser.token directly over sample lines and asserts the styles.
// Run with `jlpm test` (compiles src/lean4.ts to .test-build/ first).
const assert = require('assert');
const { StringStream } = require('@codemirror/language');
const { leanParser } = require('../.test-build/lean4.js');

/** Tokenize `lines` as one continuous document; returns [text, style] pairs. */
function tokenize(lines) {
  const state = leanParser.startState(2);
  const out = [];
  for (const line of lines) {
    const stream = new StringStream(line, 2, 2);
    while (!stream.eol()) {
      stream.start = stream.pos;
      const style = leanParser.token(stream, state);
      assert.ok(stream.pos > stream.start, `no progress on: ${line}`);
      if (style) {
        out.push([line.slice(stream.start, stream.pos), style]);
      }
    }
  }
  return out;
}

function check(lines, expected) {
  const got = tokenize(Array.isArray(lines) ? lines : [lines]);
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

check('prefer bar', [['prefer', 'keyword'], ['bar', 'variableName']]);

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
