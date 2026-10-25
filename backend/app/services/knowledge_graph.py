"""Conservative Python AST extraction for the project-scoped code graph.

The existing parser fallback indexes several languages, but this graph extractor
currently makes semantic claims only for Python, where the standard AST parser is
available in every supported runtime.
"""

import ast
import re
from dataclasses import dataclass, field
from pathlib import PurePosixPath


@dataclass
class NodeSpec:
    kind: str
    name: str
    qualified_name: str
    path: str
    start_line: int
    end_line: int


@dataclass
class EdgeSpec:
    source: str
    target_name: str
    relation: str
    path: str
    start_line: int
    end_line: int
    target: str | None = None
    resolution: str = "unresolved"
    binding: str | None = None


@dataclass
class GraphSpec:
    nodes: list[NodeSpec] = field(default_factory=list)
    edges: list[EdgeSpec] = field(default_factory=list)


def _module_name(path: str) -> str:
    parts = list(PurePosixPath(path).with_suffix("").parts)
    if parts and parts[-1] == "__init__":
        parts.pop()
    return ".".join(parts) or path


def _call_name(node: ast.AST) -> str | None:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        prefix = _call_name(node.value)
        return f"{prefix}.{node.attr}" if prefix else node.attr
    return None


class _PythonGraphVisitor(ast.NodeVisitor):
    def __init__(self, path: str, module_name: str, result: GraphSpec):
        self.path = path
        self.module_name = module_name
        self.result = result
        self.scope = [module_name]
        self.function_nodes: list[NodeSpec] = []

    @property
    def current(self) -> str:
        return self.scope[-1]

    def visit_ClassDef(self, node: ast.ClassDef):
        self._visit_expression_fields(node, {"body"})
        qualified = f"{self.current}.{node.name}"
        item = NodeSpec("class", node.name, qualified, self.path, node.lineno, getattr(node, "end_lineno", node.lineno))
        self.result.nodes.append(item)
        self.result.edges.append(EdgeSpec(self.current, qualified, "contains", self.path, node.lineno, getattr(node, "end_lineno", node.lineno), qualified, "direct"))
        self.scope.append(qualified)
        for statement in node.body:
            self.visit(statement)
        self.scope.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef):
        self._visit_function(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef):
        self._visit_function(node)

    def _visit_function(self, node: ast.FunctionDef | ast.AsyncFunctionDef):
        self._visit_expression_fields(node, {"body"})
        qualified = f"{self.current}.{node.name}"
        kind = "method" if any(spec.kind == "class" and self.current == spec.qualified_name for spec in self.result.nodes) else "function"
        item = NodeSpec(kind, node.name, qualified, self.path, node.lineno, getattr(node, "end_lineno", node.lineno))
        self.result.nodes.append(item)
        self.function_nodes.append(item)
        self.result.edges.append(EdgeSpec(self.current, qualified, "contains", self.path, node.lineno, getattr(node, "end_lineno", node.lineno), qualified, "direct"))
        self.scope.append(qualified)
        for statement in node.body:
            self.visit(statement)
        self.scope.pop()

    def _visit_expression_fields(self, node: ast.AST, excluded: set[str]):
        # Decorators, bases, defaults and annotations execute/evaluate in the
        # enclosing scope; only the body belongs to the new lexical entity.
        for field_name, value in ast.iter_fields(node):
            if field_name in excluded:
                continue
            if isinstance(value, ast.AST):
                self.visit(value)
            elif isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        self.visit(item)

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            self.result.edges.append(EdgeSpec(
                self.current, alias.name, "import", self.path, node.lineno, node.lineno,
                binding=alias.asname or alias.name.split(".")[0],
            ))

    def visit_ImportFrom(self, node: ast.ImportFrom):
        module = ("." * node.level) + (node.module or "")
        for alias in node.names:
            target = f"{module}:{alias.name}"
            self.result.edges.append(EdgeSpec(
                self.current, target, "import", self.path, node.lineno, node.lineno,
                binding=alias.asname or alias.name,
            ))

    def visit_Call(self, node: ast.Call):
        target_name = _call_name(node.func)
        if target_name:
            self.result.edges.append(EdgeSpec(self.current, target_name, "calls", self.path, node.lineno, getattr(node, "end_lineno", node.lineno)))
        self.generic_visit(node)


def extract_python_graph(source: str, path: str) -> GraphSpec:
    """Extract Python file/module/declaration/import/call graph facts.

    Syntax errors yield a file and module node only; no inferred relationships are
    emitted from incomplete syntax trees.
    """
    lines = source.splitlines()
    end_line = max(len(lines), 1)
    module = _module_name(path)
    result = GraphSpec(nodes=[
        NodeSpec("file", PurePosixPath(path).name, path, path, 1, end_line),
        NodeSpec("module", module.rsplit(".", 1)[-1], module, path, 1, end_line),
    ])
    result.edges.append(EdgeSpec(path, module, "contains", path, 1, end_line, module, "direct"))
    try:
        tree = ast.parse(source, filename=path)
    except (SyntaxError, ValueError):
        return result
    visitor = _PythonGraphVisitor(path, module, result)
    visitor.visit(tree)

    return result


def _walk_tree(node):
    yield node
    for child in node.named_children:
        yield from _walk_tree(child)


def _ts_text(node, source: bytes) -> str:
    return source[node.start_byte:node.end_byte].decode("utf-8", errors="replace")


def _tree_sitter_module(root, source: bytes, path: str, language: str) -> str:
    if language == "java":
        package = next((node for node in root.named_children if node.type == "package_declaration"), None)
        if package:
            value = _ts_text(package, source).removeprefix("package").removesuffix(";").strip()
            return value or _module_name(path)
    return _module_name(path)


def extract_tree_sitter_graph(source_text: str, path: str, language: str) -> GraphSpec:
    """Extract conservative semantic facts for Java, JavaScript, and TypeScript.

    Broken syntax returns file/module nodes only. Relationship targets remain
    unresolved unless the indexer can bind them to a unique local declaration.
    """
    from tree_sitter import Language, Parser
    import tree_sitter_java as tsjava
    import tree_sitter_javascript as tsjs
    import tree_sitter_typescript as tsts

    grammars = {
        "java": Language(tsjava.language()),
        "javascript": Language(tsjs.language()),
        "typescript": Language(tsts.language_typescript() if language == "typescript" else tsts.language_tsx()),
    }
    grammar = grammars.get(language)
    if grammar is None:
        return GraphSpec()

    source = source_text.encode("utf-8")
    parser = Parser(grammar)
    tree = parser.parse(source)
    root = tree.root_node
    module = _tree_sitter_module(root, source, path, language)
    result = GraphSpec(nodes=[
        NodeSpec("file", PurePosixPath(path).name, path, path, 1, max(1, len(source_text.splitlines()))),
        NodeSpec("module", module.rsplit(".", 1)[-1], module, path, 1, max(1, len(source_text.splitlines()))),
    ])
    result.edges.append(EdgeSpec(path, module, "contains", path, 1, max(1, len(source_text.splitlines())), module, "direct"))
    if root.has_error:
        return result

    class_types = {"class_declaration", "abstract_class_declaration", "enum_declaration", "record_declaration"}
    interface_types = {"interface_declaration", "annotation_type_declaration"}
    function_types = {"function_declaration", "generator_function_declaration", "method_definition", "method_declaration", "method_signature", "abstract_method_signature", "constructor_declaration"}
    import_types = {"import_statement", "import_declaration"}

    def add_entity(kind, name, node, parent, parent_is_class):
        qualified = f"{parent}.{name}"
        item = NodeSpec(
            "method" if kind == "function" and parent_is_class else kind,
            name,
            qualified,
            path,
            node.start_point.row + 1,
            node.end_point.row + 1,
        )
        result.nodes.append(item)
        result.edges.append(EdgeSpec(parent, qualified, "contains", path, item.start_line, item.end_line, qualified, "direct"))
        return qualified

    def visit(node, scope, scope_is_class=False):
        node_type = node.type
        if node_type in class_types | interface_types | function_types:
            name_node = node.child_by_field_name("name")
            if name_node is not None:
                name = _ts_text(name_node, source)
                kind = "interface" if node_type in interface_types else "class" if node_type in class_types else "function"
                qualified = add_entity(kind, name, node, scope, scope_is_class)
                if kind in {"class", "interface"}:
                    heritage = []
                    for field_name, relation in (("superclass", "inherits"), ("interfaces", "implements"), ("super_interfaces", "implements"), ("extends_interfaces", "inherits")):
                        base = node.child_by_field_name(field_name)
                        if base is not None:
                            heritage.append((base, relation))
                    for child in node.named_children:
                        if child.type == "class_heritage":
                            found_clause = False
                            for clause in child.named_children:
                                if clause.type == "extends_clause":
                                    heritage.append((clause, "inherits"))
                                    found_clause = True
                                elif clause.type == "implements_clause":
                                    heritage.append((clause, "implements"))
                                    found_clause = True
                            if not found_clause and child.named_children:
                                heritage.append((child, "inherits"))
                        elif child.type == "extends_type_clause":
                            heritage.append((child, "inherits"))
                    for base, relation in heritage:
                        for candidate in _walk_tree(base):
                            reference_types = {"type_identifier", "identifier", "scoped_identifier"}
                            ancestor = candidate.parent
                            nested_reference = False
                            while ancestor is not None and ancestor != base.parent:
                                if ancestor.type in reference_types:
                                    nested_reference = True
                                    break
                                if ancestor == base:
                                    break
                                ancestor = ancestor.parent
                            if candidate.type in reference_types and not nested_reference:
                                target_name = _ts_text(candidate, source)
                                if target_name and target_name != name:
                                    result.edges.append(EdgeSpec(qualified, target_name, relation, path, candidate.start_point.row + 1, candidate.end_point.row + 1))
                    visit_children(node, qualified, True)
                else:
                    visit_children(node, qualified, False)
                return

        # Arrow/function expressions assigned to const/let/var become named functions.
        if node_type == "variable_declarator":
            name_node = node.child_by_field_name("name")
            value_node = node.child_by_field_name("value")
            if name_node is not None and value_node is not None and value_node.type in {"arrow_function", "function_expression", "generator_function"}:
                name = _ts_text(name_node, source)
                qualified = add_entity("function", name, value_node, scope, scope_is_class)
                visit_children(value_node, qualified, False)
                for child in node.named_children:
                    if child != name_node and child != value_node:
                        visit(child, scope, scope_is_class)
                return

        if node_type in import_types:
            raw = _ts_text(node, source).strip()
            if language == "java":
                target = raw.removeprefix("import").removesuffix(";").strip()
                target = target.removeprefix("static ").removesuffix(".*")
            else:
                quoted = [candidate for candidate in _walk_tree(node) if candidate.type in {"string", "string_fragment"}]
                target = _ts_text(quoted[-1], source).strip("'\"`) ") if quoted else raw
            if target:
                if language == "java":
                    result.edges.append(EdgeSpec(scope, target, "import", path, node.start_point.row + 1, node.end_point.row + 1, binding=target.rsplit(".", 1)[-1]))
                elif language in {"javascript", "typescript"}:
                    named = re.search(r"\{([^}]*)\}", raw)
                    bindings = []
                    if named:
                        for entry in named.group(1).split(","):
                            item = re.fullmatch(r"\s*([\w$]+)(?:\s+as\s+([\w$]+))?\s*", entry)
                            if item:
                                imported, binding = item.groups()
                                bindings.append((f"{target}:{imported}", binding or imported))
                    default = re.match(r"\s*import\s+([\w$]+)\s*(?:,|from\s)", raw)
                    if default:
                        bindings.append((target, default.group(1)))
                    namespace = re.search(r"\*\s+as\s+([\w$]+)", raw)
                    if namespace:
                        bindings.append((target, namespace.group(1)))
                    for imported_target, binding in bindings or [(target, None)]:
                        result.edges.append(EdgeSpec(scope, imported_target, "import", path, node.start_point.row + 1, node.end_point.row + 1, binding=binding))
                else:
                    result.edges.append(EdgeSpec(scope, target, "import", path, node.start_point.row + 1, node.end_point.row + 1))

        if node_type in {"call_expression", "method_invocation", "object_creation_expression", "new_expression"}:
            fn = node.child_by_field_name("function") or node.child_by_field_name("name") or node.child_by_field_name("type")
            if node_type == "method_invocation":
                receiver = node.child_by_field_name("object")
                method = node.child_by_field_name("name")
                if receiver is not None and method is not None:
                    fn = None
                    target = f"{_ts_text(receiver, source)}.{_ts_text(method, source)}"
                else:
                    target = _ts_text(fn, source) if fn is not None else ""
            else:
                target = _ts_text(fn, source) if fn is not None else ""
            if target:
                result.edges.append(EdgeSpec(scope, target, "calls", path, node.start_point.row + 1, node.end_point.row + 1))

        visit_children(node, scope, scope_is_class)

    def visit_children(node, scope, scope_is_class):
        for child in node.named_children:
            visit(child, scope, scope_is_class)

    visit(root, module)
    return result
