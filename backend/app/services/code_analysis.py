"""Deterministic, bounded repository health metrics and review rules."""

import ast
import hashlib
import re
from collections import Counter, defaultdict


SECRET_ASSIGN = re.compile(
    r"(?i)\b[A-Za-z0-9_-]*(?:api[_-]?key|secret|password|passwd|token)[A-Za-z0-9_-]*\b\s*[:=]\s*(['\"])([^'\"]{8,})\1"
)
SECRET_PLACEHOLDERS = {"changeme", "replace_me", "your_key_here", "example", "xxxxxxxx"}


def _masked(line: str) -> str:
    return SECRET_ASSIGN.sub(lambda match: match.group(0).replace(match.group(2), "[REDACTED]"), line)


def _finding(rule, severity, category, title, description, remediation, path, start, end, evidence):
    safe_evidence = _masked(evidence)[:500]
    finding_id = hashlib.sha256(f"{rule}|{path}|{start}|{end}|{safe_evidence}".encode()).hexdigest()[:24]
    return {
        "id": finding_id,
        "rule_id": rule,
        "severity": severity,
        "category": category,
        "title": title,
        "description": description,
        "remediation": remediation,
        "path": path,
        "start_line": start,
        "end_line": end,
        "evidence": safe_evidence,
        "origin": "static_rule",
        "confidence": "rule_match",
    }


def _python_complexities(source: str):
    try:
        tree = ast.parse(source)
    except (SyntaxError, ValueError):
        return []
    results = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            decisions = sum(1 for item in ast.walk(node) if isinstance(item, (
                ast.If, ast.For, ast.AsyncFor, ast.While, ast.ExceptHandler,
                ast.IfExp, ast.comprehension, ast.Match, ast.BoolOp,
            )))
            complexity = 1 + decisions
            results.append({
                "name": node.name,
                "start_line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno),
                "complexity": complexity,
            })
    return results


def _code_line(line: str, language: str) -> bool:
    trimmed = line.strip()
    if not trimmed:
        return False
    if language == "python":
        return not trimmed.startswith("#")
    return not trimmed.startswith(("//", "/*", "*", "*/"))


def analyze_documents(documents, dependencies=(), graph_nodes=(), graph_edges=()):
    """Return metrics and rule-confirmed findings without contacting an LLM."""
    findings = []
    total_lines = 0
    languages = Counter()
    complexities = []
    duplicate_windows = defaultdict(list)

    for doc in documents:
        source_lines = doc.content.splitlines()
        total_lines += sum(_code_line(line, doc.language) for line in source_lines)
        languages[doc.language] += 1

        rules = [
            (re.compile(r"\b(?:eval|exec)\s*\("), "SEC-DYNAMIC-EVAL", "high", "security", "Dynamic code execution call", "This rule detects a call site, not proof of an exploitable vulnerability.", "Avoid evaluating untrusted strings; prefer explicit parsing or dispatch."),
            (re.compile(r"\bshell\s*=\s*True\b"), "SEC-SHELL-TRUE", "high", "security", "Subprocess enables shell interpretation", "Shell interpretation can make argument construction unsafe when input is untrusted.", "Pass an argument array and keep shell=False; validate any external input."),
            (re.compile(r"\bpickle\.(?:loads?|Unpickler)\s*\("), "SEC-PICKLE-LOAD", "high", "security", "Unsafe deserialization API", "Python pickle loading can execute behavior from untrusted serialized data.", "Do not load untrusted pickle data; use a constrained data format."),
            (re.compile(r"(?i)\b(?:execute|executemany)\s*\(\s*f[\"']"), "SEC-SQL-FSTRING", "high", "security", "Interpolated SQL call", "An f-string is passed directly to a database execution method; this is a risk pattern, not proof of user-controlled input.", "Use parameterized query placeholders and bind values separately."),
        ]
        for number, line in enumerate(source_lines, 1):
            secret = SECRET_ASSIGN.search(line)
            if secret and secret.group(2).strip().lower() not in SECRET_PLACEHOLDERS:
                findings.append(_finding("SEC-HARDCODED-CREDENTIAL", "high", "security", "Credential-like literal", "A credential-named variable contains a non-placeholder string literal. The literal is redacted in this report; validate whether it is a real secret.", "Move credentials to a secret manager or backend environment configuration and rotate any real exposed value.", doc.path, number, number, line))
            for pattern, rule, severity, category, title, description, remediation in rules:
                if pattern.search(line):
                    findings.append(_finding(rule, severity, category, title, description, remediation, doc.path, number, number, line))
            if re.search(r"\b(?:TODO|FIXME|HACK)\b", line):
                findings.append(_finding("MAINT-TODO", "low", "maintainability", "Unresolved code note", "A TODO, FIXME, or HACK marker remains in source.", "Confirm the note is still needed and track it or remove it after resolving the work.", doc.path, number, number, line))

        functions = _python_complexities(doc.content) if doc.language == "python" else []
        complexities.extend({**item, "path": doc.path} for item in functions)
        for item in functions:
            if item["complexity"] > 10:
                excerpt = "\n".join(source_lines[item["start_line"] - 1:item["end_line"]])
                findings.append(_finding("MAINT-COMPLEXITY", "medium", "maintainability", "High cyclomatic complexity", f"{item['name']} has an approximate cyclomatic complexity of {item['complexity']} using Python AST decision points.", "Split independent branches into small functions and add focused tests around each path.", doc.path, item["start_line"], item["end_line"], excerpt))
        # Exact normalized eight-line windows provide a conservative duplicate signal.
        normalized = []
        for number, line in enumerate(source_lines, 1):
            if _code_line(line, doc.language):
                normalized.append((re.sub(r"\s+", " ", line.strip()), number))
        for offset in range(max(0, len(normalized) - 7)):
            block = normalized[offset:offset + 8]
            signature = "\n".join(item[0] for item in block)
            if len(signature) >= 100:
                duplicate_windows[hashlib.sha256(signature.encode()).hexdigest()].append((doc.path, block[0][1], block[-1][1], signature))

    for matches in duplicate_windows.values():
        paths = {item[0] for item in matches}
        if len(paths) < 2:
            continue
        for path, start, end, signature in matches:
            findings.append(_finding("MAINT-DUPLICATE-BLOCK", "low", "duplication", "Repeated source block", "An exact normalized eight-line block appears in another indexed file; verify whether this is intentional shared boilerplate.", "Consider extracting shared behavior when the blocks represent the same responsibility.", path, start, end, signature))

    severity_rank = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
    findings.sort(key=lambda item: (severity_rank[item["severity"]], item["path"], item["start_line"], item["rule_id"]))
    incoming = Counter()
    entity_lookup = {node.id: node for node in graph_nodes}
    for edge in graph_edges:
        if edge.target_node_id:
            incoming[edge.target_node_id] += 1
    hotspots = [
        {"path": entity_lookup[node_id].source_path, "symbol": entity_lookup[node_id].qualified_name, "references": count, "start_line": entity_lookup[node_id].start_line}
        for node_id, count in incoming.most_common(10) if node_id in entity_lookup and count > 1
    ]
    if not hotspots:
        dependency_counts = Counter(dep.target for dep in dependencies)
        hotspots = [{"path": None, "symbol": symbol, "references": count, "start_line": None} for symbol, count in dependency_counts.most_common(10) if count > 1]
    python_files = [doc for doc in documents if doc.language == "python"]
    health = {
        "total_files": len(documents),
        "source_lines": total_lines,
        "language_distribution": dict(sorted(languages.items())),
        "entity_counts": dict(Counter(node.kind for node in graph_nodes)),
        "dependency_hotspots": hotspots,
        "complexity": {
            "available": bool(python_files),
            "analyzed_functions": len(complexities) if python_files else None,
            "average_python_cyclomatic": round(sum(item["complexity"] for item in complexities) / len(complexities), 2) if complexities else (0 if python_files else None),
            "high_complexity_functions": sum(item["complexity"] > 10 for item in complexities) if python_files else None,
            "definition": "Approximate Python AST decisions + 1; only Python functions are included.",
        },
        "duplicates": {"available": True, "finding_count": sum(item["rule_id"] == "MAINT-DUPLICATE-BLOCK" for item in findings), "definition": "Exact normalized eight-code-line windows shared across different indexed files."},
        "test_coverage": {"available": False, "value": None, "reason": "No reliable coverage artifact is attached to this indexed revision."},
        "findings_by_severity": dict(Counter(item["severity"] for item in findings)),
    }
    return health, findings

