from dataclasses import dataclass
import re

@dataclass
class CodeChunk:
    symbol: str
    symbol_type: str
    start_line: int
    end_line: int
    content: str
    imports: list[str]

EXT = {".py":"python", ".java":"java", ".js":"javascript", ".jsx":"javascript", ".ts":"typescript", ".tsx":"typescript"}

try:
    from tree_sitter import Language, Parser
    import tree_sitter_python as tspython
    import tree_sitter_javascript as tsjs
    import tree_sitter_typescript as tsts
    import tree_sitter_java as tsjava
    LANGS = {
        "python": Language(tspython.language()),
        "javascript": Language(tsjs.language()),
        "typescript": Language(tsts.language_typescript()),
        "java": Language(tsjava.language()),
    }
except Exception:
    LANGS = {}

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

def parse_code(text: str, language: str):
    # Tree-sitter is attempted for supported languages; regex fallback keeps ingestion resilient.
    if language in LANGS:
        try:
            parser=Parser(LANGS[language])
            tree=parser.parse(text.encode())
            if not tree.root_node.has_error:
                # Symbol extraction is intentionally conservative; regex gives stable line ranges.
                return _regex_chunks(text,language)
        except Exception:
            pass
    return _regex_chunks(text,language)
