import { StreamParser, StringStream } from "@codemirror/language";
import { tags } from "@lezer/highlight";

/*
 * A syntax-highlighting definition for the CasDsl language — the surface
 * grammar of the lean-cas-dsl project (CasDsl/Syntax.lean). The kernel cells
 * are NOT Lean 4: they are parsed by the `casTerm`/`casRel`/`casAssertion`
 * categories and the `let`/`assert`/bare-term command set that module
 * declares. This file mirrors that grammar's TOKEN inventory; the word lists
 * below are held one-to-one to the lists the grammar's own parse guard
 * maintains (Syntax.lean `reservedWords` / `nonReservedKeywords`), and the
 * test suite pins every word.
 *
 * Style mapping (one token kind per grammar construct):
 * - reserved words, non-reserved keywords, command words      -> keyword
 * - the five domain tokens and their backslash spellings      -> typeName
 * - symbolic constants (π, e, i, ℵ₀, 𝒫, ∞)                    -> atom
 * - relations, operators, arrows, √ ∫ ∑ ∏, dx/dt, punctuation -> operator
 * - comments / strings / numbers / meta follow Lean's lexical rules,
 *   because the cell text is still tokenized by Lean before the DSL parser
 *   sees it (a `--` comment, a `"..."` literal, a `#eval` command all exist
 *   in a cell's source).
 */

/** Syntax.lean:480 — REAL tokens: an identifier by any of these spellings
 * cannot be written anywhere, including as a binding name. Exported so the
 * test suite can pin every word by iterating the list. */
export const RESERVED_WORDS = ["dx", "Spec", "lim_", "map", "to", "is"];

/** Syntax.lean:485 — `&"…"` keywords the grammar keys on WITHOUT reserving;
 * they stay ordinary identifiers everywhere else. Exported for the test
 * suite's exhaustive pin. */
export const NON_RESERVED_KEYWORDS = ["and", "O", "dt", "span_QQ"];

/** The command words of the surface: `let` (three spellings, Syntax.lean
 * :964/:973/:983), `assert` (:993), and the `in`/`∈` ambient-and-binder tail
 * that is also the ASCII relation spelling (`casRelIn`, :495). Exported for
 * the test suite's exhaustive pin. */
export const COMMAND_WORDS = ["let", "assert", "in"];

/** Symbolic constants — `π`, `e`, `i` from `Eval.constantValue?` (with `e`
 * and `i` reserved symbols a binding may never shadow), plus the two symbol
 * TOKENS whose spellings lex as identifiers: `ℵ₀` (ℵ is a letter, ₀ a number)
 * and `𝒫` (script capital P is a letter). `d` is the differential — one of the
 * two shadowable constants of the reserved surface ("d, π | shadowable
 * constants"), styled like its sibling `π`. `∞` is not an identifier character
 * and is matched as a token of its own below. Exported for the test suite. */
export const CONSTANT_ATOMS = ["π", "e", "i", "ℵ₀", "𝒫", "d"];

/** The five domain tokens (Syntax.lean :45–:49) and their backslash spellings
 * (:58–:62). Exported for the test suite. */
export const DOMAIN_TOKENS = [
  "ℕ",
  "ℤ",
  "ℚ",
  "ℝ",
  "ℂ",
  "\\NN",
  "\\ZZ",
  "\\QQ",
  "\\RR",
  "\\CC",
];

// CasDsl identifiers are Unicode, same lexical rule as Lean: `𝔽₂`, `ℤ`, `α`,
// `foo'`, `bar!`, `baz?`. Two deliberate carve-outs, both pinned to the
// grammar:
// - the SUPERSxript digits ⁰¹²³⁴⁵⁶⁷⁸⁹ are Unicode numbers too, but the
//   grammar's `casSup` productions (Syntax.lean :374, :390) make them POWER
//   tokens — `x²` is `x^2` and `ℚ³` is `ℚ^3`, never one name — so they are
//   excluded from identifier continuation (they still lex, as operators).
//   SUBscript digits (₀₁₂₃…, U+2080–U+2089) are ordinary identifier
//   characters (`u₁`, `h₁`, `x₀`) and stay in.
// - `_` is NOT an identifier start here: the grammar writes it only as the
//   binder-marker token of `∑_{…}` and `lim_{…}` (Syntax.lean :158, :405).
//   It remains an identifier CONTINUATION character (`span_QQ`, `lim_`).
const IDENT =
  /^[\p{L}](?:(?![\u00B9\u00B2\u00B3\u2070-\u2079])[\p{L}\p{N}_'!?])*/u;
const NUMBER = /^(0[xX][0-9a-fA-F]+|0[bB][01]+|\d+(\.\d+)?)/;
const HASH_COMMAND = /^#[\p{L}_][\p{L}\p{N}_]*/u;
const CHAR_LITERAL = /^'(\\.|[^\\'])'/;

export interface ICasState {
  /** Nesting depth of block comments; 0 when outside one. */
  depth: number;
  /** Whether the outermost open block comment is a doc comment. */
  doc: boolean;
}

/** Consume the rest of an open block comment, tracking nesting. */
function tokenBlockComment(stream: StringStream, state: ICasState): string {
  const style = state.doc ? "docComment" : "comment";
  while (!stream.eol()) {
    if (stream.match("-/")) {
      state.depth -= 1;
      if (state.depth === 0) {
        state.doc = false;
        return style;
      }
      continue;
    }
    if (stream.match("/-")) {
      state.depth += 1;
      continue;
    }
    stream.next();
  }
  return style;
}

function token(
  keywords: Set<string>,
  constants: Set<string>,
  domains: Set<string>,
  stream: StringStream,
  state: ICasState,
): string | null {
  if (state.depth > 0) {
    return tokenBlockComment(stream, state);
  }
  if (stream.eatSpace()) {
    return null;
  }

  if (stream.match("--")) {
    stream.skipToEnd();
    return "comment";
  }
  if (stream.match("/--")) {
    state.depth = 1;
    state.doc = true;
    return tokenBlockComment(stream, state);
  }
  if (stream.match("/-")) {
    state.depth = 1;
    state.doc = false;
    return tokenBlockComment(stream, state);
  }

  if (stream.peek() === '"') {
    stream.next();
    let escaped = false;
    while (!stream.eol()) {
      const ch = stream.next();
      if (escaped) {
        escaped = false;
      } else if (ch === "\\") {
        escaped = true;
      } else if (ch === '"') {
        break;
      }
    }
    return "string";
  }
  if (stream.match(CHAR_LITERAL)) {
    return "string";
  }

  if (stream.match(NUMBER)) {
    return "number";
  }
  // #eval, #check, ... — a genuine Lean command token, which a cell may hold.
  if (stream.match(HASH_COMMAND)) {
    return "meta";
  }

  // `∞` is a symbol, not an identifier character; the other symbolic atoms
  // (π, e, i, ℵ₀, 𝒫) lex as identifiers and are resolved below.
  if (stream.match("∞")) {
    return "atom";
  }

  // The backslash family — the LaTeX spellings the grammar admits beside the
  // unicode tokens: the domains (\NN…) and the operator spellings
  // (\in, \leq, \mapsto). A lone backslash is the set difference `\`.
  if (
    stream.match("\\mapsto") ||
    stream.match("\\leq") ||
    stream.match("\\in")
  ) {
    return "operator";
  }
  if (
    stream.match("\\NN") ||
    stream.match("\\ZZ") ||
    stream.match("\\QQ") ||
    stream.match("\\RR") ||
    stream.match("\\CC")
  ) {
    return "typeName";
  }

  const ident = stream.match(IDENT);
  if (ident) {
    const word = (ident as RegExpMatchArray)[0];
    if (keywords.has(word)) {
      return "keyword";
    }
    if (domains.has(word)) {
      return "typeName";
    }
    if (constants.has(word)) {
      return "atom";
    }
    return "variableName";
  }

  // Dot methods — `z.re()`, `A.det()`, `n.factor()`: the category system
  // attaches methods to values and the surface spells the call with a dot. A
  // `.` immediately followed by an identifier is one method token; a lone dot
  // stays structural punctuation.
  if (stream.peek() === ".") {
    const save = stream.pos;
    stream.next();
    if (stream.match(IDENT)) {
      return "methodName";
    }
    stream.pos = save;
  }

  // Multi-char ASCII operators kept as single tokens; `...` is the ellipsis
  // of set literals and index families.
  if (stream.match(":=") || stream.match("|->") || stream.match("->")) {
    return "operator";
  }
  if (stream.match("...")) {
    return "operator";
  }
  // Everything else — relations (∈ ∉ ⊆ = ≠), comparisons (≤ ≥ < >), the
  // binary operators (∘ ∩ × ∪ △ · / ^ + -), arrows (→ ↦), the structural
  // tokens ( ( ) { } [ ] | , ; _ : . ), superscripts (⁰¹²³…), subscripts
  // (₀₁₂₃…), ⁻¹, √ ∫ ∑ ∏, the bars, and the single `\` set difference.
  stream.next();
  return "operator";
}

/** Build a parser for the CasDsl surface grammar. The word lists are closed:
 * they ARE the grammar's, so no extra-keywords knob exists here (unlike the
 * generic Lean 4 parser next door). */
export function makeCasDslParser(): StreamParser<ICasState> {
  const keywords = new Set([
    ...RESERVED_WORDS,
    ...NON_RESERVED_KEYWORDS,
    ...COMMAND_WORDS,
  ]);
  const constants = new Set(CONSTANT_ATOMS);
  const domains = new Set(DOMAIN_TOKENS);
  return {
    name: "casdsl",

    startState: () => ({ depth: 0, doc: false }),

    token: (stream, state) =>
      token(keywords, constants, domains, stream, state),

    languageData: {
      commentTokens: { line: "--", block: { open: "/-", close: "-/" } },
    },

    tokenTable: {
      docComment: tags.docComment,
      typeName: tags.typeName,
      atom: tags.atom,
      // Style strings map to tags by KEY: the parser emits `methodName`, so
      // the table key is `methodName` even though the tag is `propertyName`.
      methodName: tags.propertyName,
    },
  };
}
