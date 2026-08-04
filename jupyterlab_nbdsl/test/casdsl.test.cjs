// Drives makeCasDslParser.token directly over sample lines and asserts the
// styles, then drives the full render pipeline (parser → tree → tags → DOM
// spans). Run with `jlpm test` (compiles src/casdsl.ts to .test-build/ first).
//
// Every word in CasDsl/Syntax.lean's `reservedWords` and
// `nonReservedKeywords`, and every command word, is pinned below by iterating
// the lists src/casdsl.ts exports — a grammar rewrite on the Lean side must
// be mirrored in the TS lists, and this file fails if any listed word does
// not lex as a keyword. The parse guard in CasDslTests/Core.lean holds the
// Lean lists to the grammar the same way.
const assert = require('assert');
const { StringStream } = require('@codemirror/language');
const casdsl = require('../.test-build/casdsl.js');
const { makeCasDslParser } = casdsl;

const casParser = makeCasDslParser();

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

function check(lines, expected, parser = casParser) {
  const got = tokenize(Array.isArray(lines) ? lines : [lines], parser);
  assert.deepStrictEqual(got, expected, JSON.stringify(got));
}

// The language is NOT Lean 4: Lean's own keywords are ordinary identifiers.
check('theorem t : x = 1 := by s' + 'orry', [
  ['theorem', 'variableName'],
  ['t', 'variableName'],
  [':', 'operator'],
  ['x', 'variableName'],
  ['=', 'operator'],
  ['1', 'number'],
  [':=', 'operator'],
  ['by', 'variableName'],
  ['s' + 'orry', 'variableName']
]);

// Commands — every spelling the grammar declares (Syntax.lean :964/:972/:982
// /:992/:1004).
check('assert 2 + 3 = 5', [
  ['assert', 'keyword'],
  ['2', 'number'],
  ['+', 'operator'],
  ['3', 'number'],
  ['=', 'operator'],
  ['5', 'number']
]);

check('assert 2 + 3 = 0 in ℤ/5', [
  ['assert', 'keyword'],
  ['2', 'number'],
  ['+', 'operator'],
  ['3', 'number'],
  ['=', 'operator'],
  ['0', 'number'],
  ['in', 'keyword'],
  ['ℤ', 'typeName'],
  ['/', 'operator'],
  ['5', 'number']
]);

check('let n := 360 in ℤ', [
  ['let', 'keyword'],
  ['n', 'variableName'],
  [':=', 'operator'],
  ['360', 'number'],
  ['in', 'keyword'],
  ['ℤ', 'typeName']
]);

check('let p(x) := x^5 - x^4 - x^3 + x^2 - 2x + 2 in ℤ[x]', [
  ['let', 'keyword'],
  ['p', 'variableName'],
  ['(', 'operator'],
  ['x', 'variableName'],
  [')', 'operator'],
  [':=', 'operator'],
  ['x', 'variableName'],
  ['^', 'operator'],
  ['5', 'number'],
  ['-', 'operator'],
  ['x', 'variableName'],
  ['^', 'operator'],
  ['4', 'number'],
  ['-', 'operator'],
  ['x', 'variableName'],
  ['^', 'operator'],
  ['3', 'number'],
  ['+', 'operator'],
  ['x', 'variableName'],
  ['^', 'operator'],
  ['2', 'number'],
  ['-', 'operator'],
  ['2', 'number'],
  ['x', 'variableName'],
  ['+', 'operator'],
  ['2', 'number'],
  ['in', 'keyword'],
  ['ℤ', 'typeName'],
  ['[', 'operator'],
  ['x', 'variableName'],
  [']', 'operator']
]);

check('let φ: ℚ³ → ℚ := n ↦ 2n', [
  ['let', 'keyword'],
  ['φ', 'variableName'],
  [':', 'operator'],
  ['ℚ', 'typeName'],
  ['³', 'operator'],
  ['→', 'operator'],
  ['ℚ', 'typeName'],
  [':=', 'operator'],
  ['n', 'variableName'],
  ['↦', 'operator'],
  ['2', 'number'],
  ['n', 'variableName']
]);

// casDef — `NAME := e [in T]` without the `let`.
check('q := map p to ℂ[x]', [
  ['q', 'variableName'],
  [':=', 'operator'],
  ['map', 'keyword'],
  ['p', 'variableName'],
  ['to', 'keyword'],
  ['ℂ', 'typeName'],
  ['[', 'operator'],
  ['x', 'variableName'],
  [']', 'operator']
]);

// The ⊆-chain — `and` is a conjunction of assertions.
check('assert ℤ ⊆ ℚ and ℚ ⊆ ℝ and ℝ ⊆ ℂ', [
  ['assert', 'keyword'],
  ['ℤ', 'typeName'],
  ['⊆', 'operator'],
  ['ℚ', 'typeName'],
  ['and', 'keyword'],
  ['ℚ', 'typeName'],
  ['⊆', 'operator'],
  ['ℝ', 'typeName'],
  ['and', 'keyword'],
  ['ℝ', 'typeName'],
  ['⊆', 'operator'],
  ['ℂ', 'typeName']
]);

// Reserved words — Syntax.lean `reservedWords` (:480). Every exported entry
// must lex as a keyword.
for (const word of casdsl.RESERVED_WORDS) {
  check(word, [[word, 'keyword']]);
}

// Non-reserved keywords — Syntax.lean `nonReservedKeywords` (:485).
for (const word of casdsl.NON_RESERVED_KEYWORDS) {
  check(word, [[word, 'keyword']]);
}

// Command words — `let` (:964/:973/:983), `assert` (:993), and the `in`
// relation tail (:495). Standalone, each is a keyword token.
for (const word of casdsl.COMMAND_WORDS) {
  check(word, [[word, 'keyword']]);
}

// A segment CONTAINING a reserved word is an untouched identifier.
check('is_prime e1 span', [
  ['is_prime', 'variableName'],
  ['e1', 'variableName'],
  ['span', 'variableName']
]);

// Domains, unicode and backslash spellings — every exported entry.
for (const d of casdsl.DOMAIN_TOKENS) {
  check(d, [[d, 'typeName']]);
}

// Symbolic constants. `∞` is a symbol token matched outside the identifier
// rule, so it is not in CONSTANT_ATOMS — pinned separately here.
for (const c of [...casdsl.CONSTANT_ATOMS, '∞']) {
  check(c, [[c, 'atom']]);
}
check('e^t', [['e', 'atom'], ['^', 'operator'], ['t', 'variableName']]);
check('2 + 2i', [
  ['2', 'number'],
  ['+', 'operator'],
  ['2', 'number'],
  ['i', 'atom']
]);

// Dot methods — the category methods of the surface (`z.re()`, `A.det()`,
// `n.factor()`): a dot immediately followed by an identifier is one method
// token; a lone dot stays structural punctuation.
check('n.factor()', [
  ['n', 'variableName'],
  ['.factor', 'methodName'],
  ['(', 'operator'],
  [')', 'operator']
]);
check('(360).factor()', [
  ['(', 'operator'],
  ['360', 'number'],
  [')', 'operator'],
  ['.factor', 'methodName'],
  ['(', 'operator'],
  [')', 'operator']
]);
check('z.re()', [
  ['z', 'variableName'],
  ['.re', 'methodName'],
  ['(', 'operator'],
  [')', 'operator']
]);
check('d(f) = (6x + 1) dx', [
  ['d', 'atom'],
  ['(', 'operator'],
  ['f', 'variableName'],
  [')', 'operator'],
  ['=', 'operator'],
  ['(', 'operator'],
  ['6', 'number'],
  ['x', 'variableName'],
  ['+', 'operator'],
  ['1', 'number'],
  [')', 'operator'],
  ['dx', 'keyword']
]);

// Set spellings.
check('{x ∈ X | P(x)}', [
  ['{', 'operator'],
  ['x', 'variableName'],
  ['∈', 'operator'],
  ['X', 'variableName'],
  ['|', 'operator'],
  ['P', 'variableName'],
  ['(', 'operator'],
  ['x', 'variableName'],
  [')', 'operator'],
  ['}', 'operator']
]);
check('{n in ℕ | f(n) ∈ 2ℕ}', [
  ['{', 'operator'],
  ['n', 'variableName'],
  ['in', 'keyword'],
  ['ℕ', 'typeName'],
  ['|', 'operator'],
  ['f', 'variableName'],
  ['(', 'operator'],
  ['n', 'variableName'],
  [')', 'operator'],
  ['∈', 'operator'],
  ['2', 'number'],
  ['ℕ', 'typeName'],
  ['}', 'operator']
]);
check('2^{1, 2, 3}', [
  ['2', 'number'],
  ['^', 'operator'],
  ['{', 'operator'],
  ['1', 'number'],
  [',', 'operator'],
  ['2', 'number'],
  [',', 'operator'],
  ['3', 'number'],
  ['}', 'operator']
]);

// Analysis spellings: integrals, limits, aggregates, series, coefficients.
check('∫₀¹ t² dt', [
  ['∫', 'operator'],
  ['₀', 'operator'],
  ['¹', 'operator'],
  ['t', 'variableName'],
  ['²', 'operator'],
  ['dt', 'keyword']
]);
check('∫ f dx', [['∫', 'operator'], ['f', 'variableName'], ['dx', 'keyword']]);
check('lim_{t → 0} sin(t)/t', [
  ['lim_', 'keyword'],
  ['{', 'operator'],
  ['t', 'variableName'],
  ['→', 'operator'],
  ['0', 'number'],
  ['}', 'operator'],
  ['sin', 'variableName'],
  ['(', 'operator'],
  ['t', 'variableName'],
  [')', 'operator'],
  ['/', 'operator'],
  ['t', 'variableName']
]);
check('∑_{n ∈ ℕ} n²', [
  ['∑', 'operator'],
  ['_', 'operator'],
  ['{', 'operator'],
  ['n', 'variableName'],
  ['∈', 'operator'],
  ['ℕ', 'typeName'],
  ['}', 'operator'],
  ['n', 'variableName'],
  ['²', 'operator']
]);
check('ℝ[[t]]/(t^6)', [
  ['ℝ', 'typeName'],
  ['[', 'operator'],
  ['[', 'operator'],
  ['t', 'variableName'],
  [']', 'operator'],
  [']', 'operator'],
  ['/', 'operator'],
  ['(', 'operator'],
  ['t', 'variableName'],
  ['^', 'operator'],
  ['6', 'number'],
  [')', 'operator']
]);
check('ℤ[[t]] / O(t^5)', [
  ['ℤ', 'typeName'],
  ['[', 'operator'],
  ['[', 'operator'],
  ['t', 'variableName'],
  [']', 'operator'],
  [']', 'operator'],
  ['/', 'operator'],
  ['O', 'keyword'],
  ['(', 'operator'],
  ['t', 'variableName'],
  ['^', 'operator'],
  ['5', 'number'],
  [')', 'operator']
]);
check('[t^2]f', [
  ['[', 'operator'],
  ['t', 'variableName'],
  ['^', 'operator'],
  ['2', 'number'],
  [']', 'operator'],
  ['f', 'variableName']
]);

// Bars, radical, powerset, span, comparison chains, arrows.
check('|A|', [['|', 'operator'], ['A', 'variableName'], ['|', 'operator']]);
check('2√2', [['2', 'number'], ['√', 'operator'], ['2', 'number']]);
check('𝒫(ℤ)', [
  ['𝒫', 'atom'],
  ['(', 'operator'],
  ['ℤ', 'typeName'],
  [')', 'operator']
]);
check('span_QQ{u₁, u₂} \\leq ℚ³', [
  ['span_QQ', 'keyword'],
  ['{', 'operator'],
  ['u₁', 'variableName'],
  [',', 'operator'],
  ['u₂', 'variableName'],
  ['}', 'operator'],
  ['\\leq', 'operator'],
  ['ℚ', 'typeName'],
  ['³', 'operator']
]);
check('assert 0 ≤ n < 6', [
  ['assert', 'keyword'],
  ['0', 'number'],
  ['≤', 'operator'],
  ['n', 'variableName'],
  ['<', 'operator'],
  ['6', 'number']
]);
check('f |-> g', [
  ['f', 'variableName'],
  ['|->', 'operator'],
  ['g', 'variableName']
]);
check('f \\mapsto g', [
  ['f', 'variableName'],
  ['\\mapsto', 'operator'],
  ['g', 'variableName']
]);
check('M⁻¹ b', [
  ['M', 'variableName'],
  ['⁻', 'operator'],
  ['¹', 'operator'],
  ['b', 'variableName']
]);
check('assert S in 𝒫(ℤ)', [
  ['assert', 'keyword'],
  ['S', 'variableName'],
  ['in', 'keyword'],
  ['𝒫', 'atom'],
  ['(', 'operator'],
  ['ℤ', 'typeName'],
  [')', 'operator']
]);

// The shared lexical layer — comments, strings, numbers, meta, identifiers.
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

// Unicode identifiers survive intact (ℤ is a DOMAIN here, unlike the Lean
// parser's plain-identifier treatment).
check('𝔽₂ ℤ h₁ x✝ → ∈', [
  ['𝔽₂', 'variableName'],
  ['ℤ', 'typeName'],
  ['h₁', 'variableName'],
  ['x', 'variableName'],
  ['✝', 'operator'],
  ['→', 'operator'],
  ['∈', 'operator']
]);

// Primed identifiers are one token, not an identifier plus a char literal.
check("foo' bar", [["foo'", 'variableName'], ['bar', 'variableName']]);

// The full render path — stream parser → syntax tree → style tags → DOM.
// Runs the same pipeline the notebook editor does and asserts the span
// classes JupyterLab's standard `tok-*` theme rules target. Uses
// `tagHighlighter`, the @lezer/highlight API this package's ^1.0.0 range
// actually pins (`HighlightStyle`/`defaultHighlightStyle` were added later
// and are not available at 1.2.3).
const { JSDOM } = require('jsdom');
const w = new JSDOM(
  '<!doctype html><html><body><div id="host"></div></body></html>',
  { pretendToBeVisual: true }
).window;
for (const k of Object.getOwnPropertyNames(w)) {
  if (k in global) continue;
  try {
    global[k] = w[k];
  } catch (e) {
    /* accessor that throws (location) — not needed */
  }
}
const stubMM = (q) => ({
  matches: false,
  media: q,
  onchange: null,
  addListener() {},
  removeListener() {},
  addEventListener() {},
  removeEventListener() {},
  dispatchEvent() {
    return false;
  },
});
w.matchMedia = stubMM;
global.matchMedia = stubMM;
if (typeof global.IntersectionObserver === 'undefined') {
  global.IntersectionObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
    takeRecords() {
      return [];
    }
  };
}
if (typeof global.CSS === 'undefined') {
  global.CSS = { supports: () => false };
}
if (typeof w.HTMLElement.prototype.scrollIntoView !== 'function') {
  w.HTMLElement.prototype.scrollIntoView = function () {};
}
if (typeof global.DataTransfer === 'undefined') {
  global.DataTransfer = class {
    constructor() {
      this.items = [];
      this.files = [];
      this.types = [];
    }
    getData() {
      return '';
    }
    setData() {}
    clearData() {}
  };
}
if (typeof global.DragEvent === 'undefined') {
  global.DragEvent = class DragEvent extends MouseEvent {
    constructor(type, init = {}) {
      super(type, init);
      this.dataTransfer = init.dataTransfer || new DataTransfer();
    }
  };
}
if (typeof global.ClipboardEvent === 'undefined') {
  global.ClipboardEvent = class ClipboardEvent extends Event {
    constructor(type, init = {}) {
      super(type, init);
      this.clipboardData = init.clipboardData || null;
    }
  };
}
if (typeof global.ResizeObserver === 'undefined') {
  global.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}

const { EditorView } = require('@codemirror/view');
const {
  LanguageSupport,
  StreamLanguage,
  syntaxHighlighting,
} = require('@codemirror/language');
const { tagHighlighter, tags } = require('@lezer/highlight');

const tokStyle = tagHighlighter([
  { tag: tags.keyword, class: 'tok-keyword' },
  { tag: tags.typeName, class: 'tok-typeName' },
  { tag: tags.atom, class: 'tok-atom' },
  { tag: tags.number, class: 'tok-number' },
  { tag: tags.operator, class: 'tok-operator' },
  { tag: tags.comment, class: 'tok-comment' },
  { tag: tags.string, class: 'tok-string' },
  { tag: tags.meta, class: 'tok-meta' },
  { tag: tags.propertyName, class: 'tok-propertyName' },
  { tag: tags.variableName, class: 'tok-variableName' },
]);

function renderSpans(doc) {
  const view = new EditorView({
    doc,
    extensions: [
      new LanguageSupport(StreamLanguage.define(makeCasDslParser())),
      syntaxHighlighting(tokStyle),
    ],
    parent: document.getElementById('host'),
  });
  return [...view.contentDOM.querySelectorAll('span')].map((s) => [
    s.className,
    s.textContent,
  ]);
}

assert.deepStrictEqual(renderSpans('assert 2 + 3 = 5 in ℤ'), [
  ['tok-keyword', 'assert'],
  ['tok-number', '2'],
  ['tok-operator', '+'],
  ['tok-number', '3'],
  ['tok-operator', '='],
  ['tok-number', '5'],
  ['tok-keyword', 'in'],
  ['tok-typeName', 'ℤ'],
]);

assert.deepStrictEqual(renderSpans('z.re()'), [
  ['tok-variableName', 'z'],
  ['tok-propertyName', '.re'],
  ['tok-operator', '()'],
]);

assert.deepStrictEqual(renderSpans('d(f) = (6x + 1) dx'), [
  ['tok-atom', 'd'],
  ['tok-operator', '('],
  ['tok-variableName', 'f'],
  ['tok-operator', ')'],
  ['tok-operator', '='],
  ['tok-operator', '('],
  ['tok-number', '6'],
  ['tok-variableName', 'x'],
  ['tok-operator', '+'],
  ['tok-number', '1'],
  ['tok-operator', ')'],
  ['tok-keyword', 'dx'],
]);

console.log('casdsl: all checks passed');
