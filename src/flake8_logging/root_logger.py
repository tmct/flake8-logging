from __future__ import annotations

import ast
from collections import Counter


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
    """Track local root loggers and unambiguous module bindings used in functions."""

    def __init__(self, logger_methods: frozenset[str]) -> None:
        self.errors: list[tuple[int, int]] = []
        self._logger_methods = logger_methods
        self._bindings: dict[str, str] = {}
        self._module_functions: list[ast.FunctionDef | ast.AsyncFunctionDef] = []

    def visit_Module(self, node: ast.Module) -> None:
        # Deferred bodies see module globals, not their values at definition time.
        # Only inherit names with a single module binding and no global declaration.
        writes: Counter[str] = Counter()
        for statement in node.body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                writes.update([statement.name])
                expressions = [
                    *statement.decorator_list,
                    *statement.args.defaults,
                    *statement.args.kw_defaults,
                ]
            elif isinstance(statement, ast.ClassDef):
                writes.update([statement.name])
                expressions = [
                    *statement.decorator_list,
                    *statement.bases,
                    *(keyword.value for keyword in statement.keywords),
                ]
            else:
                writes.update(bound_names(statement))
                expressions = []
            for expression in expressions:
                if expression is not None:
                    writes.update(bound_names(expression))

        global_names = {
            name
            for child in ast.walk(node)
            if isinstance(child, ast.Global)
            for name in child.names
        }
        self._visit_body(node.body, module_level=True)
        module_bindings = {
            name: "module_root" if kind == "root" else kind
            for name, kind in self._bindings.items()
            if writes[name] == 1 and name not in global_names
        }
        for function in self._module_functions:
            self._visit_function(function, module_bindings)

    def _visit_function(
        self,
        node: ast.FunctionDef | ast.AsyncFunctionDef,
        inherited: dict[str, str],
    ) -> None:
        outer_bindings = self._bindings
        local_names = bound_names(node.args)
        for statement in node.body:
            local_names.update(bound_names(statement))
        self._bindings = {
            name: kind for name, kind in inherited.items() if name not in local_names
        }
        self._visit_body(node.body)
        self._bindings = outer_bindings

    def _collect_methods(self, node: ast.ClassDef) -> None:
        # Class attributes do not form an enclosing scope for methods' bare names.
        for statement in node.body:
            if isinstance(statement, (ast.FunctionDef, ast.AsyncFunctionDef)):
                self._module_functions.append(statement)
            elif isinstance(statement, ast.ClassDef):
                self._collect_methods(statement)

    def _visit_body(self, body: list[ast.stmt], module_level: bool = False) -> None:
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
                if module_level:
                    self._module_functions.append(statement)
                else:
                    self._visit_function(
                        statement,
                        {
                            name: kind
                            for name, kind in self._bindings.items()
                            if kind != "root"
                        },
                    )
                self._bindings.pop(statement.name, None)
            elif isinstance(statement, ast.ClassDef) and module_level:
                self._collect_methods(statement)
                for expression in (
                    *statement.decorator_list,
                    *statement.bases,
                    *(keyword.value for keyword in statement.keywords),
                ):
                    self._forget_bindings(expression)
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
                        self._bindings[target.id] = (
                            "root" if kind == "module_root" else kind
                        )
            else:
                self._forget_bindings(statement)
                # Within control flow, only module roots that cannot be locally
                # rebound are safe to check without following execution order.
                if any(
                    isinstance(child, (ast.stmt, ast.ExceptHandler, ast.match_case))
                    for child in ast.iter_child_nodes(statement)
                ):
                    outer_bindings = self._bindings
                    self._bindings = {
                        name: kind
                        for name, kind in outer_bindings.items()
                        if kind == "module_root"
                    }
                    self.visit(statement)
                    self._bindings = outer_bindings
                else:
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
            and self._bindings.get(node.func.value.id) in ("root", "module_root")
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
    visit_FunctionDef = visit_Lambda
    visit_AsyncFunctionDef = visit_Lambda
    visit_ClassDef = visit_Lambda
