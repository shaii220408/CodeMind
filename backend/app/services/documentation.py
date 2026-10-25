"""Source-referenced Markdown drafts built only from indexed repository facts."""

import ast
import re
from pathlib import PurePosixPath
from urllib.parse import quote


def _ref(path, start=1, end=None):
    suffix = f"#L{start}" + (f"-L{end}" if end and end != start else "")
    label = path.replace("`", "\\`").replace("[", "\\[").replace("]", "\\]")
    return f"[`{label}`]({quote(path, safe='/-._')}{suffix})"


def _python_routes(document):
    try:
        tree = ast.parse(document.content)
    except (SyntaxError, ValueError):
        return []
    found = []
    route_objects = set()
    methods = {"get", "post", "put", "patch", "delete", "options", "head", "websocket"}
    for node in ast.walk(tree):
        value = node.value if isinstance(node, (ast.Assign, ast.AnnAssign)) else None
        if not isinstance(value, ast.Call):
            continue
        constructor = value.func
        constructor_name = constructor.id if isinstance(constructor, ast.Name) else constructor.attr if isinstance(constructor, ast.Attribute) else ""
        if constructor_name not in {"FastAPI", "APIRouter"}:
            continue
        targets = node.targets if isinstance(node, ast.Assign) else [node.target]
        route_objects.update(target.id for target in targets if isinstance(target, ast.Name))
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        for decorator in node.decorator_list:
            call = decorator if isinstance(decorator, ast.Call) else None
            target = call.func if call else decorator
            if (not isinstance(target, ast.Attribute) or target.attr.lower() not in methods or not call or not call.args
                    or not isinstance(target.value, ast.Name) or target.value.id not in route_objects):
                continue
            first = call.args[0]
            if isinstance(first, ast.Constant) and isinstance(first.value, str) and first.value.startswith("/"):
                found.append({"method": target.attr.upper(), "path": first.value, "name": node.name, "line": decorator.lineno})
    return found


def _python_descriptions(document):
    try:
        tree = ast.parse(document.content)
    except (SyntaxError, ValueError):
        return []
    output = []
    module_doc = ast.get_docstring(tree)
    if module_doc:
        output.append({"kind": "module", "name": PurePosixPath(document.path).stem, "description": module_doc.splitlines()[0], "line": 1})
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            description = ast.get_docstring(node)
            output.append({"kind": "class" if isinstance(node, ast.ClassDef) else "function", "name": node.name, "description": description.splitlines()[0] if description else None, "line": node.lineno, "end_line": getattr(node, "end_lineno", node.lineno)})
    return output


def generate_project_documents(project, documents, graph_nodes, graph_edges):
    files = sorted(documents, key=lambda item: item.path)
    languages = {}
    for document in files:
        languages[document.language] = languages.get(document.language, 0) + 1
    refs = [_ref(document.path) for document in files[:40]]
    output = []
    overview = [f"# {project.name}: project overview", "", "Generated from the indexed snapshot. Statements below describe indexed files and statically extracted entities.", "", "## Snapshot facts", f"- Index revision: `{project.index_revision}`", f"- Indexed files: {len(files)}", f"- Languages: " + (", ".join(f"{name} ({count})" for name, count in sorted(languages.items())) or "none"), f"- Source files: {', '.join(refs) if refs else 'none'}"]
    output.append({"kind": "overview", "title": "Project overview", "scope_key": "", "markdown": "\n".join(overview), "source_refs": [document.path for document in files[:40]]})

    readmes = [document for document in files if PurePosixPath(document.path).name.lower().startswith("readme")]
    manifests = [document.path for document in files if PurePosixPath(document.path).name.lower() in {"package.json", "pyproject.toml", "requirements.txt", "cargo.toml", "go.mod", "pom.xml", "build.gradle", "docker-compose.yml", "dockerfile"}]
    setup = ["# Setup guide draft", "", "This draft reports setup information found in the indexed snapshot. It does not infer commands or dependency versions.", "", "## Detected manifest/configuration files"]
    setup.extend(f"- {_ref(path)}" for path in manifests)
    setup_sources = set(manifests)
    if not manifests:
        setup.append("- No recognized dependency or runtime manifest was found.")
    setup.append("\n## Existing setup instructions")
    for readme in readmes[:3]:
        matches = list(re.finditer(r"(?ims)^```[^\n]*\n(.*?)^```\s*$", readme.content))
        if matches:
            setup.append(f"\nInstructions copied from {_ref(readme.path)}:")
            for match in matches[:5]:
                block = match.group(1).strip()
                if block:
                    setup.append("```text\n" + block[:2400] + "\n```")
            setup_sources.add(readme.path)
        else:
            setup.append(f"\nReview {_ref(readme.path)} for repository-specific instructions. No command was inferred by this generator.")
            setup_sources.add(readme.path)
    if not readmes:
        setup.append("No README setup instructions were indexed; this remains an incomplete setup draft.")
    output.append({"kind": "setup", "title": "Setup guide draft", "scope_key": "", "markdown": "\n".join(setup), "source_refs": sorted(setup_sources)})

    by_path = {}
    for node in graph_nodes:
        if node.kind in {"class", "interface", "function", "method", "module"}:
            by_path.setdefault(node.source_path, []).append(node)
    python_by_path = {document.path: document for document in files if document.language == "python"}
    for path in sorted(set(by_path) | set(python_by_path)):
        declarations = sorted(by_path.get(path, []), key=lambda node: (node.start_line, node.kind, node.qualified_name))
        descriptions = {(item["name"], item["line"]): item for item in _python_descriptions(python_by_path[path])} if path in python_by_path else {}
        lines = [f"# Module: `{path}`", "", f"Source: {_ref(path)}", "", "## Extracted declarations"]
        if not declarations and not descriptions:
            lines.append("No supported declarations were extracted from this file.")
        for node in declarations:
            description = descriptions.get((node.name, node.start_line), {}).get("description")
            text = f" — {description}" if description else " — No docstring description was present; only the declaration name and source range are known."
            lines.append(f"- **{node.kind.title()} `{node.qualified_name}`** ({_ref(path, node.start_line, node.end_line)}){text}")
        module_description = descriptions.get((PurePosixPath(path).stem, 1))
        if module_description and module_description.get("kind") == "module":
            lines.insert(3, f"\nModule summary: {module_description['description']}")
        output.append({"kind": "module", "title": f"Module: {path}", "scope_key": path, "markdown": "\n".join(lines), "source_refs": [path]})

    routes = []
    for document in files:
        if document.language == "python":
            routes.extend((document.path, route) for route in _python_routes(document))
    api_lines = ["# Detected API routes", "", "Only literal route paths in Python decorators were included. Other frameworks or dynamically built paths may not be detected.", ""]
    if routes:
        api_lines.extend(["| Method | Path | Handler | Source |", "|---|---|---|---|"])
        api_lines.extend(f"| {route['method']} | `{route['path']}` | `{route['name']}` | {_ref(path, route['line'])} |" for path, route in sorted(routes, key=lambda item: (item[1]["path"], item[1]["method"])))
    else:
        api_lines.append("No API routes could be reliably identified in the indexed Python files.")
    output.append({"kind": "api", "title": "Detected API documentation", "scope_key": "", "markdown": "\n".join(api_lines), "source_refs": sorted({path for path, _ in routes})})

    node_by_id = {node.id: node for node in graph_nodes}
    architecture = ["# Extracted architecture", "", "```mermaid", "graph TD"]
    represented = set()
    links = []
    for edge in graph_edges:
        if edge.target_node_id and edge.source_node_id in node_by_id and edge.target_node_id in node_by_id and edge.relation in {"import", "inherits", "implements"}:
            source, target = node_by_id[edge.source_node_id], node_by_id[edge.target_node_id]
            source_id = "n" + re.sub(r"[^A-Za-z0-9_]", "_", source.id)
            target_id = "n" + re.sub(r"[^A-Za-z0-9_]", "_", target.id)
            represented.update((source.id, target.id))
            links.append((source_id, target_id, edge.relation, source, target))
    for node_id in sorted(represented):
        node = node_by_id[node_id]
        safe_label = (node.qualified_name or node.name).replace('"', "'")
        architecture.append(f'  n{re.sub(r"[^A-Za-z0-9_]", "_", node.id)}["{safe_label}"]')
    for source_id, target_id, relation, _source, _target in links:
        architecture.append(f"  {source_id} -->|{relation}| {target_id}")
    if not links:
        architecture.append("  NoResolvedEdges[\"No resolved import or inheritance edges\"]")
    architecture.extend(["```", "", "Unresolved relationships are omitted from this diagram rather than guessed."])
    output.append({"kind": "architecture", "title": "Architecture explanation", "scope_key": "", "markdown": "\n".join(architecture), "source_refs": sorted({node_by_id[item].source_path for item in represented})})
    return output

