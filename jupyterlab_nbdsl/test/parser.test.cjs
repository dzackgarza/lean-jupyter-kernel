// Drives leanParser.token directly over sample lines and asserts the styles.
// Run with `jlpm test` (compiles src/lean4.ts to .test-build/ first).
const assert = require('assert');
const { StringStream } = require('@codemirror/language');
const {
  makeLean4Parser,
  DEFAULT_DSL_KEYWORDS,
} = require('../.test-build/lean4.js');

// Production default: the CasDsl surface plus the legacy NbDsl keyword.
const leanParser = makeLean4Parser(DEFAULT_DSL_KEYWORDS);

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
  [':=', 'operator'],
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

// Regression: `assert` is the DSL's command word (casdsl.ts COMMAND_WORDS);
// cells resolving to text/x-lean4 must highlight it. Was variableName —
// the "zero syntax highlighting" the user reported on demo.ipynb.
check('assert 2 + 3 = 5 in ℤ', [
  ['assert', 'keyword'],
  ['2', 'number'],
  ['+', 'operator'],
  ['3', 'number'],
  ['=', 'operator'],
  ['5', 'number'],
  ['in', 'keyword'],
  ['ℤ', 'atom']
]);

// The rest of the CasDsl reserved surface highlights under the default too.
check('map p to ℚ[x] is Spec', [
  ['map', 'keyword'],
  ['p', 'variableName'],
  ['to', 'keyword'],
  ['ℚ', 'atom'],
  ['[', 'operator'],
  ['x', 'variableName'],
  [']', 'operator'],
  ['is', 'keyword'],
  ['Spec', 'keyword']
]);

// Dot methods — the CasDsl category system spells method calls `.factor()`.
// The method identifier must not fall back to plain variableName (the
// reported "factor() not highlighted" symptom). One `.ident` token.
check('f.factor()', [
  ['f', 'variableName'],
  ['.factor', 'methodName'],
  ['(', 'operator'],
  [')', 'operator']
]);

// A lone dot stays structural punctuation (`x.5`), not a method.
check('x.5', [
  ['x', 'variableName'],
  ['.', 'operator'],
  ['5', 'number']
]);

// The differential: `d` is an atom (casdsl CONSTANT_ATOMS), `dx` a reserved
// keyword (Syntax.lean:480) — `d/dx` must highlight the d, not just dx.
check('d/dx', [
  ['d', 'atom'],
  ['/', 'operator'],
  ['dx', 'keyword']
]);
check('d(f)', [
  ['d', 'atom'],
  ['(', 'operator'],
  ['f', 'variableName'],
  [')', 'operator']
]);
check('π = 3.14', [
  ['π', 'atom'],
  ['=', 'operator'],
  ['3.14', 'number']
]);
check('ℚ[x]', [
  ['ℚ', 'atom'],
  ['[', 'operator'],
  ['x', 'variableName'],
  [']', 'operator']
]);

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
  [':=', 'operator'],
  ['by', 'keyword'],
  ['s' + 'orry', 'invalid']
]);

// Unicode identifiers must survive intact. (ℤ is a domain atom now — use α.)
check('𝔽₂ α h₁ x✝ → ∈', [
  ['𝔽₂', 'variableName'],
  ['α', 'variableName'],
  ['h₁', 'variableName'],
  ['x', 'variableName'],
  ['✝', 'operator'],
  ['→', 'operator'],
  ['∈', 'operator']
]);

// Primed identifiers are one token, not an identifier plus a char literal.
check("foo' bar", [["foo'", 'variableName'], ['bar', 'variableName']]);

console.log('parser: all checks passed');
