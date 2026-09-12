from __future__ import annotations

import ast


def bound_names(node: ast.AST) -> set[str]:
    """Conservatively collect bindings, including inside unsupported constructs."""
    names = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, (ast.Store, ast.Del)):
            names.add(child.id)
        elif isinstance(child, ast.alias):
            names.add(child.asname or child.name.split(".")[0])
        elif isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(child.name)
        elif isinstance(child, ast.arg):
            names.add(child.arg)
        elif isinstance(child, (ast.Global, ast.Nonlocal)):
            names.update(child.names)
        elif isinstance(child, (ast.ExceptHandler, ast.MatchAs, ast.MatchStar)):
            if child.name:
                names.add(child.name)
        elif isinstance(child, ast.MatchMapping) and child.rest:
            names.add(child.rest)
    return names


class RootLoggerVisitor(ast.NodeVisitor):
    """Track definite root loggers through straight-line statements in one scope."""

    def __init__(self, logger_methods: frozenset[str]) -> None:
        self.errors: list[tuple[int, int]] = []
        self._logger_methods = logger_methods
        self._bindings: dict[str, str] = {}

    def visit_Module(self, node: ast.Module) -> None:
        self._visit_body(node.body)

    def _visit_body(self, body: list[ast.stmt]) -> None:
        for statement in body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                for expression in (
                    *statement.decorator_list,
                    *statement.args.defaults,
                    *statement.args.kw_defaults,
                ):
                    if expression is not None:
                        self._forget_bindings(expression)
                        self.visit(expression)
                outer_bindings = self._bindings
                local_names = bound_names(statement)
                self._bindings = {
                    name: kind
                    for name, kind in outer_bindings.items()
                    if kind != "root" and name not in local_names
                }
                self._visit_body(statement.body)
                self._bindings = outer_bindings
                self._bindings.pop(statement.name, None)
            elif isinstance(statement, (ast.Import, ast.ImportFrom)):
                for alias in statement.names:
                    name = alias.asname or alias.name.split(".")[0]
                    self._bindings.pop(name, None)
                    if isinstance(statement, ast.Import) and alias.name == "logging":
                        self._bindings[name] = "module"
                    elif (
                        isinstance(statement, ast.ImportFrom)
                        and statement.level == 0
                        and statement.module == "logging"
                        and alias.name == "getLogger"
                    ):
                        self._bindings[name] = "factory"
                    elif alias.name == "*":
                        self._bindings.clear()
            elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
                value = statement.value
                # A bare annotation does not replace an existing value.
                if value is None:
                    continue
                self._forget_bindings(value)
                self.visit(value)
                kind = self._binding(value)
                targets = (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else [statement.target]
                )
                for target in targets:
                    self._forget_bindings(target)
                    if isinstance(target, ast.Name) and kind is not None:
                        self._bindings[target.id] = kind
            else:
                self._forget_bindings(statement)
                # Skip control flow and class bodies: AST order is not execution
                # order. Still forget bindings they might replace before moving on.
                if not any(
                    isinstance(child, (ast.stmt, ast.ExceptHandler, ast.match_case))
                    for child in ast.iter_child_nodes(statement)
                ):
                    self.visit(statement)
                if isinstance(
                    statement, (ast.Return, ast.Raise, ast.Break, ast.Continue)
                ):
                    break

    def _forget_bindings(self, node: ast.AST) -> None:
        names = bound_names(node)
        if "*" in names:
            self._bindings.clear()
        for name in names:
            self._bindings.pop(name, None)

    def _binding(self, node: ast.expr) -> str | None:
        if isinstance(node, ast.Name):
            return self._bindings.get(node.id)
        if (
            isinstance(node, ast.Attribute)
            and node.attr == "getLogger"
            and isinstance(node.value, ast.Name)
            and self._bindings.get(node.value.id) == "module"
        ):
            return "factory"
        if (
            isinstance(node, ast.Call)
            and not node.args
            and not node.keywords
            and self._binding(node.func) == "factory"
        ):
            return "root"
        return None

    def visit_Call(self, node: ast.Call) -> None:
        if (
            isinstance(node.func, ast.Attribute)
            and node.func.attr in self._logger_methods
            and isinstance(node.func.value, ast.Name)
            and self._bindings.get(node.func.value.id) == "root"
        ):
            self.errors.append((node.lineno, node.col_offset))
        self.generic_visit(node)

    def visit_Lambda(self, node: ast.AST) -> None:
        # Deferred execution and comprehension scopes require separate analysis.
        pass

    visit_ListComp = visit_Lambda
    visit_SetComp = visit_Lambda
    visit_DictComp = visit_Lambda
    visit_GeneratorExp = visit_Lambda
