import hashlib
import os
import re
import shutil
import zipfile
from pathlib import Path, PurePosixPath

from sqlalchemy import delete, select

from app.models.models import Chunk, Dependency, Document, GraphEdge, GraphNode, Project
from app.parsers.code_parser import EXT, parse_code
from app.services.embedding import embed_many
from app.services.knowledge_graph import extract_python_graph, extract_tree_sitter_graph

IGNORE = {".git", "node_modules", "target", "build", "dist", ".venv", "__pycache__"}


def safe_extract(zip_path: str, dest: str, max_bytes: int, max_files: int = 10000):
    total_bytes = 0
    file_count = 0
    with zipfile.ZipFile(zip_path) as archive:
        for info in archive.infolist():
            normalized = info.filename.replace("\\", "/")
            name = Path(normalized)
            if (
                name.is_absolute()
                or ".." in name.parts
                or normalized.startswith("/")
                or (len(normalized) >= 2 and normalized[1] == ":")
                or ((info.external_attr >> 16) & 0o170000) == 0o120000
            ):
                raise ValueError("Unsafe ZIP path")
            if not info.is_dir():
                file_count += 1
                if file_count > max_files:
                    raise ValueError("Archive exceeds configured file-count limit")
            total_bytes += info.file_size
            if total_bytes > max_bytes:
                raise ValueError("Archive exceeds configured size limit")
            if any(part in IGNORE for part in name.parts):
                continue
            target = Path(dest, name)
            target.parent.mkdir(parents=True, exist_ok=True)
            if not info.is_dir():
                with archive.open(info) as src, open(target, "wb") as dst:
                    shutil.copyfileobj(src, dst)


def scan_files(root: str):
    for path in Path(root).rglob("*"):
        if path.is_symlink() or not path.is_file() or any(part in IGNORE for part in path.parts):
            continue
        if path.suffix.lower() not in EXT or path.stat().st_size > 2_000_000:
            continue
        try:
            yield path, EXT[path.suffix.lower()], path.read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue


def index_repository(db, project_id: str, root: str, generation: int | None = None, repository_metadata: dict | None = None):
    # Serialize duplicate Celery deliveries for a project. The complete document,
    # dependency and graph update commits together below.
    project = db.scalar(select(Project).where(Project.id == project_id).with_for_update())
    if project is None:
        raise ValueError("Project does not exist")
    if generation is not None and generation != project.index_generation:
        db.rollback()
        return "SKIPPED_STALE"
    old = {doc.path: doc for doc in db.scalars(select(Document).where(Document.project_id == project_id)).all()}
    records = []
    definitions: dict[str, set[str]] = {}
    for path, language, content in scan_files(root):
        relative_path = path.relative_to(root).as_posix()
        chunks = parse_code(content, language)
        graph = (
            extract_python_graph(content, relative_path)
            if language == "python"
            else extract_tree_sitter_graph(content, relative_path, language)
            if language in {"java", "javascript", "typescript"}
            else None
        )
        records.append((relative_path, language, content, chunks, graph))
        for match in re.finditer(r"\b(?:class|interface|enum)\s+([A-Z][A-Za-z0-9_]*)", content):
            definitions.setdefault(match.group(1), set()).add(relative_path)

    seen = set()
    dependency_keys = set()
    # Build the dependency graph from the complete snapshot, even when file hashes
    # are unchanged. These writes share the same transaction as the index update.
    db.execute(delete(Dependency).where(Dependency.project_id == project_id))

    documents = {}
    for relative_path, language, content, chunks, graph in records:
        seen.add(relative_path)
        digest = hashlib.sha256(content.encode()).hexdigest()
        document = old.get(relative_path)
        changed = document is None or document.content_hash != digest
        if document is None:
            document = Document(
                project_id=project_id,
                path=relative_path,
                language=language,
                content_hash=digest,
                content=content,
            )
            db.add(document)
            db.flush()
        elif changed:
            db.execute(delete(Chunk).where(Chunk.document_id == document.id))
            document.language = language
            document.content_hash = digest
            document.content = content
        documents[relative_path] = document

        if changed:
            vectors = embed_many([f"{relative_path}\n{chunk.symbol}\n{chunk.content}" for chunk in chunks])
            for chunk, vector in zip(chunks, vectors):
                db.add(Chunk(
                    project_id=project_id,
                    document_id=document.id,
                    symbol=chunk.symbol,
                    symbol_type=chunk.symbol_type,
                    start_line=chunk.start_line,
                    end_line=chunk.end_line,
                    content=chunk.content,
                    embedding=vector,
                    chunk_metadata={"language": language},
                ))

        for chunk in chunks:
            for imported in chunk.imports:
                key = (document.id, chunk.symbol, imported, "import")
                if key not in dependency_keys:
                    db.add(Dependency(
                        project_id=project_id,
                        source_document_id=document.id,
                        source_symbol=chunk.symbol,
                        target=imported,
                        relation_type="import",
                    ))
                    dependency_keys.add(key)
            for symbol, source_paths in definitions.items():
                if relative_path in source_paths or not re.search(rf"\b{re.escape(symbol)}\b", chunk.content):
                    continue
                key = (document.id, chunk.symbol, symbol, "symbol_reference")
                if key not in dependency_keys:
                    db.add(Dependency(
                        project_id=project_id,
                        source_document_id=document.id,
                        source_symbol=chunk.symbol,
                        target=symbol,
                        relation_type="symbol_reference",
                    ))
                    dependency_keys.add(key)

    # Rebuild graph rows from the complete snapshot in this same transaction.
    # A failed parser/index run rolls back both the old graph and document changes.
    db.execute(delete(GraphEdge).where(GraphEdge.project_id == project_id))
    db.execute(delete(GraphNode).where(GraphNode.project_id == project_id))
    db.flush()
    graph_nodes = []
    node_by_path_and_name = {}
    node_by_qualified_name = {}
    candidates_by_name = {}
    classes_by_name = {}
    modules_by_name = {}
    for relative_path, _language, _content, _chunks, graph in records:
        if graph is None:
            continue
        document = documents[relative_path]
        for spec in graph.nodes:
            node = GraphNode(
                project_id=project_id,
                document_id=document.id,
                kind=spec.kind,
                name=spec.name,
                qualified_name=spec.qualified_name,
                source_path=spec.path,
                start_line=spec.start_line,
                end_line=spec.end_line,
            )
            graph_nodes.append((spec, node))
            node_by_path_and_name[(relative_path, spec.qualified_name)] = node
            node_by_qualified_name.setdefault(spec.qualified_name, []).append(node)
            if spec.kind in {"function", "method", "class", "interface"}:
                candidates_by_name.setdefault(spec.name, []).append((spec, node))
            if spec.kind in {"class", "interface"}:
                classes_by_name.setdefault(spec.name, []).append((spec, node))
            elif spec.kind == "module":
                modules_by_name.setdefault(spec.qualified_name, []).append(node)
            db.add(node)
    db.flush()

    # Bind only unique local declarations. Cross-file Python calls require an
    # explicit from-import binding. Java static calls through an explicitly
    # imported type resolve only when the imported class and method are unique.
    # Other-language calls stay unresolved unless the target is exact and unique.
    def normalize_python_module(relative_path, module):
        if module.startswith("."):
            dots = len(module) - len(module.lstrip("."))
            source_parts = list(PurePosixPath(relative_path).with_suffix("").parts)
            package_parts = source_parts if source_parts[-1:] == ["__init__"] else source_parts[:-1]
            base = package_parts[:max(0, len(package_parts) - dots + 1)]
            module = ".".join(base + [part for part in module.lstrip(".").split(".") if part])
        return module

    modules_by_path = {
        node.source_path: name
        for name, nodes in modules_by_name.items()
        for node in nodes
    }

    def local_module_paths(relative_path, module, language):
        if language == "python":
            module = normalize_python_module(relative_path, module)
            return {node.source_path for node in modules_by_name.get(module, [])}
        if language in {"javascript", "typescript"} and module.startswith("."):
            module_path = str(PurePosixPath(relative_path).parent.joinpath(module))
            possible = {
                module_path,
                *(module_path + extension for extension in (".js", ".jsx", ".ts", ".tsx", ".mjs", ".cjs")),
                *(module_path + "/index" + extension for extension in (".js", ".jsx", ".ts", ".tsx")),
            }
            return {source_path for source_path in modules_by_path if source_path in possible}
        return set()

    def resolve_import_binding(relative_path, language, binding, import_edges):
        for imported in import_edges:
            if imported.binding != binding:
                continue
            target = imported.target_name
            if language == "java" and target in node_by_qualified_name:
                matches = node_by_qualified_name[target]
                if len(matches) == 1:
                    return matches[0].qualified_name
            module, separator, symbol = target.partition(":")
            if not separator:
                continue
            paths = local_module_paths(relative_path, module, language)
            matches = [
                (spec, node)
                for name, candidates in candidates_by_name.items()
                if name == symbol
                for spec, node in candidates
                if spec.path in paths
            ]
            if len(matches) == 1:
                return matches[0][0].qualified_name
        return None

    for relative_path, language, _content, _chunks, graph in records:
        if graph is None:
            continue
        import_edges = [edge for edge in graph.edges if edge.relation == "import"]
        for edge in graph.edges:
            if edge.target:
                continue
            if edge.relation == "calls":
                if language == "java" and "." in edge.target_name:
                    receiver, method_name = edge.target_name.rsplit(".", 1)
                    imported_type = resolve_import_binding(relative_path, language, receiver, import_edges)
                    if imported_type:
                        java_methods = [
                            node for node in node_by_qualified_name.get(f"{imported_type}.{method_name}", [])
                            if node.kind == "method"
                        ]
                        if len(java_methods) == 1:
                            edge.target = java_methods[0].qualified_name
                            edge.resolution = "inferred"
                            continue
                call_name = edge.target_name.rsplit(".", 1)[-1]
                matches = candidates_by_name.get(call_name, [])
                local = [item for item in matches if item[0].path == relative_path]
                if not local:
                    imported_target = resolve_import_binding(relative_path, language, call_name, import_edges)
                    if imported_target:
                        edge.target = imported_target
                        edge.resolution = "inferred"
                        continue
                if len(local) == 1:
                    edge.target = local[0][0].qualified_name
                    edge.resolution = "inferred"
            elif edge.relation in {"inherits", "implements"}:
                base_name = edge.target_name.rsplit(".", 1)[-1]
                matches = [item for item in classes_by_name.get(base_name, []) if item[0].path == relative_path]
                if not matches:
                    imported_target = resolve_import_binding(relative_path, language, base_name, import_edges)
                    if imported_target:
                        edge.target = imported_target
                        edge.resolution = "inferred"
                        continue
                if len(matches) == 1:
                    edge.target = matches[0][0].qualified_name
                    edge.resolution = "inferred"
            elif edge.relation == "import":
                module = edge.target_name.split(":", 1)[0]
                if language == "python":
                    module = normalize_python_module(relative_path, module)
                elif language in {"javascript", "typescript"}:
                    imported_module, _, imported_symbol = edge.target_name.partition(":")
                    paths = local_module_paths(relative_path, imported_module, language)
                    if imported_symbol:
                        symbol_matches = [
                            (spec, node)
                            for candidates in candidates_by_name.values()
                            for spec, node in candidates
                            if spec.name == imported_symbol and spec.path in paths
                        ]
                        if len(symbol_matches) == 1:
                            edge.target = symbol_matches[0][0].qualified_name
                            edge.resolution = "inferred"
                            continue
                    matches = [node for source_path in paths for name in [modules_by_path.get(source_path)] for node in modules_by_name.get(name, []) if name]
                else:
                    matches = []
                if language == "java":
                    exact_classes = node_by_qualified_name.get(edge.target_name, [])
                    if len(exact_classes) == 1:
                        edge.target = exact_classes[0].qualified_name
                        edge.resolution = "inferred"
                        continue
                if not (language in {"javascript", "typescript"} and module.startswith(".")):
                    matches = modules_by_name.get(module, [])
                if len(matches) == 1:
                    edge.target = matches[0].qualified_name
                    edge.resolution = "inferred"

    for relative_path, _language, _content, _chunks, graph in records:
        if graph is None:
            continue
        for edge in graph.edges:
            source = node_by_path_and_name.get((relative_path, edge.source))
            if source is None:
                continue
            target = None
            if edge.target:
                target = node_by_path_and_name.get((edge.path, edge.target))
                if target is None:
                    matches = node_by_qualified_name.get(edge.target, [])
                    target = matches[0] if len(matches) == 1 else None
            db.add(GraphEdge(
                project_id=project_id,
                source_node_id=source.id,
                target_node_id=target.id if target else None,
                relation=edge.relation,
                target_name=edge.target_name,
                resolution=edge.resolution if target or edge.relation == "contains" else "unresolved",
                source_path=edge.path,
                start_line=edge.start_line,
                end_line=edge.end_line,
            ))

    for relative_path, document in old.items():
        if relative_path not in seen:
            db.delete(document)
    if repository_metadata:
        project.repository_url = repository_metadata["repository_url"]
        project.repository_branch = repository_metadata["branch"]
        project.repository_commit_sha = repository_metadata["commit_sha"]
        project.sync_status = "SYNCED"
    project.index_revision += 1
    db.commit()
