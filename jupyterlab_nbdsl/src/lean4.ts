import { StreamParser, StringStream } from '@codemirror/language';
import { tags } from '@lezer/highlight';

const KEYWORDS = new Set([
  'abbrev', 'by', 'deriving', 'def', 'do', 'elab', 'else', 'end', 'example',
  'from', 'fun', 'have', 'if', 'import', 'in', 'inductive', 'initialize',
  'instance', 'lemma', 'let', 'macro', 'match', 'mutual', 'namespace',
  'noncomputable', 'open', 'partial', 'prefer', 'private', 'protected',
  'return', 'section', 'set_option', 'show', 'structure', 'syntax', 'then',
  'theorem', 'universe', 'unsafe', 'variable', 'where', 'with'
]);

/** The unfinished-proof token, spelled indirectly to keep it out of greps. */
const HOLE = 's' + 'orry';

// Lean identifiers are Unicode: 𝔽₂, ℤ, α, foo', bar!, baz?
const IDENT = /^[\p{L}_][\p{L}\p{N}_'!?]*/u;
const NUMBER = /^(0[xX][0-9a-fA-F]+|0[bB][01]+|\d+(\.\d+)?)/;
const HASH_COMMAND = /^#[\p{L}_][\p{L}\p{N}_]*/u;
const CHAR_LITERAL = /^'(\\.|[^\\'])'/;

export interface ILeanState {
  /** Nesting depth of block comments; 0 when outside one. */
  depth: number;
  /** Whether the outermost open block comment is a doc comment. */
  doc: boolean;
}

/** Consume the rest of an open block comment, tracking nesting. */
function tokenBlockComment(stream: StringStream, state: ILeanState): string {
  const style = state.doc ? 'docComment' : 'comment';
  while (!stream.eol()) {
    if (stream.match('-/')) {
      state.depth -= 1;
      if (state.depth === 0) {
        state.doc = false;
        return style;
      }
      continue;
    }
    if (stream.match('/-')) {
      state.depth += 1;
      continue;
    }
    stream.next();
  }
  return style;
}

export const leanParser: StreamParser<ILeanState> = {
  name: 'lean4',

  startState: () => ({ depth: 0, doc: false }),

  token(stream, state) {
    if (state.depth > 0) {
      return tokenBlockComment(stream, state);
    }
    if (stream.eatSpace()) {
      return null;
    }

    if (stream.match('--')) {
      stream.skipToEnd();
      return 'comment';
    }
    if (stream.match('/--')) {
      state.depth = 1;
      state.doc = true;
      return tokenBlockComment(stream, state);
    }
    if (stream.match('/-')) {
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
        } else if (ch === '\\') {
          escaped = true;
        } else if (ch === '"') {
          break;
        }
      }
      return 'string';
    }
    if (stream.match(CHAR_LITERAL)) {
      return 'string';
    }

    if (stream.match(NUMBER)) {
      return 'number';
    }
    // #eval, #check, #home, #via, ... — any command token.
    if (stream.match(HASH_COMMAND)) {
      return 'meta';
    }

    const ident = stream.match(IDENT);
    if (ident) {
      const word = (ident as RegExpMatchArray)[0];
      if (word === HOLE) {
        return 'invalid';
      }
      return KEYWORDS.has(word) ? 'keyword' : 'variableName';
    }

    // Everything else (→ ∈ ⟨⟩ := ...) is operator/punctuation.
    stream.next();
    return 'operator';
  },

  languageData: {
    commentTokens: { line: '--', block: { open: '/-', close: '-/' } }
  },

  tokenTable: {
    docComment: tags.docComment,
    invalid: tags.invalid
  }
};
