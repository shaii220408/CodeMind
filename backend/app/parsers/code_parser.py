from dataclasses import dataclass, field
import re

@dataclass
class CodeChunk:
    symbol: str
    symbol_type: str
    start_line: int
    end_line: int
    content: str
    imports: list[str]
    references: list[str] = field(default_factory=list)

EXT = {".py":"python", ".java":"java", ".js":"javascript", ".jsx":"javascript", ".ts":"typescript", ".tsx":"typescript"}

try:
    from tree_sitter import Language, Parser
    import tree_sitter_python as tspython
    import tree_sitter_javascript as tsjs
    import tree_sitter_typescript as tsts
    import tree_sitter_java as tsjava
    LANGS = {
        "python": Language(tspython.language()),
        "java": Language(tsjava.language()),
        "javascript": Language(tsjs.language()),
        "typescript": Language(tsts.language_typescript()),
    }
except Exception:
    LANGS = {}

SYMBOL_NODES = {
    "python": {
        "class_definition": "class",
        "function_definition": "function",
    },
    "javascript": {
        "class_declaration": "class",
        "function_declaration": "function",
        "generator_function_declaration": "function",
        "method_definition": "method",
        "method_signature": "method",
    },
    "typescript": {
        "class_declaration": "class",
        "abstract_class_declaration": "class",
        "interface_declaration": "interface",
        "enum_declaration": "enum",
        "function_declaration": "function",
        "generator_function_declaration": "function",
        "method_definition": "method",
        "method_signature": "method",
    },
    "java": {
        "class_declaration": "class",
        "interface_declaration": "interface",
        "enum_declaration": "enum",
        "annotation_type_declaration": "interface",
        "record_declaration": "class",
        "method_declaration": "method",
        "constructor_declaration": "constructor",
    },
}
IMPORT_NODES = {
    "import_statement", "import_from_statement", "import_declaration",
    "export_statement",
}

def _walk(node, ancestors=()):
    yield node, ancestors
    for child in node.children:
        yield from _walk(child, ancestors + (node.type,))

def _ast_chunks(text: str, language: str):
    parser = Parser(LANGS[language])
    source = text.encode("utf-8")
    tree = parser.parse(source)
    if tree.root_node.has_error:
        return None
    nodes = list(_walk(tree.root_node))
    imports = [
        source[n.start_byte:n.end_byte].decode("utf-8", errors="replace")
        for n, _ in nodes if n.type in IMPORT_NODES
    ]
    references = sorted({
        source[n.start_byte:n.end_byte].decode("utf-8", errors="replace")
        for n, _ in nodes if n.type in {"type_identifier", "scoped_type_identifier"}
    })
    found = []
    for node, ancestors in nodes:
        symbol_type = SYMBOL_NODES.get(language, {}).get(node.type)
        if not symbol_type:
            continue
        if symbol_type == "function" and any(
            t in ("class_definition", "class_declaration", "abstract_class_declaration")
            for t in ancestors
        ):
            symbol_type = "method"
        name_node = node.child_by_field_name("name")
        if name_node is None:
            continue
        name = source[name_node.start_byte:name_node.end_byte].decode("utf-8", errors="replace")
        found.append(CodeChunk(
            name, symbol_type, node.start_point.row + 1, node.end_point.row + 1,
            source[node.start_byte:node.end_byte].decode("utf-8", errors="replace"),
            imports, references,
        ))
    return found

def _regex_chunks(text: str, language: str):
    lines = text.splitlines()
    patterns = {
        "python": r"^\s*(?:async\s+def|def|class)\s+([A-Za-z_]\w*)",
        "java": r"^\s*(?:(?:public|private|protected|static|final|abstract)\s+)*(?:class|interface|enum)\s+([A-Za-z_]\w*)|^\s*(?:(?:public|private|protected|static|final)\s+)+[\w<>\[\], ?]+\s+([A-Za-z_]\w*)\s*\(",
        "javascript": r"^\s*(?:function|class)\s+([A-Za-z_$][\w$]*)|^\s*(?:export\s+)?(?:const|let|var)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(",
        "typescript": r"^\s*(?:function|class|interface|enum)\s+([A-Za-z_$][\w$]*)|^\s*(?:export\s+)?(?:const|let)\s+([A-Za-z_$][\w$]*)\s*=\s*(?:async\s*)?\(",
    }
    matches = []
    rx = re.compile(patterns.get(language, patterns["python"]))
    for i, line in enumerate(lines, 1):
        m = rx.search(line)
        if m: matches.append((i, next((g for g in m.groups() if g), "symbol")))
    chunks=[]
    for idx,(start,name) in enumerate(matches):
        end=(matches[idx+1][0]-1 if idx+1<len(matches) else len(lines))
        body="\n".join(lines[start-1:end])
        chunks.append(CodeChunk(name,"symbol",start,end,body,_imports(lines[:end],language)))
    if not chunks and lines:
        for start in range(1,len(lines)+1,80):
            end=min(len(lines),start+79)
            chunks.append(CodeChunk(f"lines_{start}_{end}","block",start,end,"\n".join(lines[start-1:end]),_imports(lines[:end],language)))
    return chunks

def _imports(lines, language):
    out=[]
    for line in lines:
        s=line.strip()
        if language=="python" and (s.startswith("import ") or s.startswith("from ")): out.append(s)
        elif language in ("javascript","typescript") and (s.startswith("import ") or s.startswith("export ")): out.append(s)
        elif language=="java" and s.startswith("import "): out.append(s)
    return out

def _bound_chunk_size(chunks, max_chars=1800):
    """Keep embedding inputs bounded while retaining symbol and exact line provenance."""
    bounded = []
    for chunk in chunks:
        lines = chunk.content.splitlines()
        pieces = []
        current = []
        current_chars = 0
        current_start = chunk.start_line

        def flush(end_line):
            nonlocal current, current_chars, current_start
            if current:
                pieces.append(("\n".join(current), current_start, end_line))
                current = []
                current_chars = 0

        for offset, line in enumerate(lines):
            line_number = chunk.start_line + offset
            if len(line) > max_chars:
                flush(line_number - 1)
                for start in range(0, len(line), max_chars):
                    pieces.append((line[start:start + max_chars], line_number, line_number))
                current_start = line_number + 1
                continue
            added_chars = len(line) + (1 if current else 0)
            if current and current_chars + added_chars > max_chars:
                flush(line_number - 1)
                current_start = line_number
            elif not current:
                current_start = line_number
            current.append(line)
            current_chars += len(line) + (1 if len(current) > 1 else 0)
        flush(chunk.start_line + len(lines) - 1)
        for index, (content, start_line, end_line) in enumerate(pieces, 1):
            symbol = chunk.symbol if len(pieces) == 1 else f"{chunk.symbol} [part {index}]"
            bounded.append(CodeChunk(
                symbol, chunk.symbol_type, start_line, max(start_line, end_line),
                content, chunk.imports, chunk.references,
            ))
    return bounded

def parse_code(text: str, language: str):
    # Use AST node boundaries where a grammar is installed; fall back per-file on parse errors.
    if language in LANGS:
        try:
            chunks = _ast_chunks(text, language)
            if chunks:
                return _bound_chunk_size(chunks)
        except Exception:
            pass
    return _bound_chunk_size(_regex_chunks(text,language))
