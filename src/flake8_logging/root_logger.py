from __future__ import annotations

import ast
from collections import Counter

Function = ast.FunctionDef | ast.AsyncFunctionDef | ast.Lambda
Comprehension = ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp


def outer_expressions(node: Function | ast.ClassDef) -> list[ast.expr]:
    if isinstance(node, ast.ClassDef):
        values = [*node.bases, *(keyword.value for keyword in node.keywords)]
    else:
        values = [
            value
            for value in (*node.args.defaults, *node.args.kw_defaults)
            if value is not None
        ]
    if not isinstance(node, ast.Lambda):
        values = [*node.decorator_list, *values]
    return values


class Bindings(ast.NodeVisitor):
    """Collect names bound in one namespace, excluding nested namespaces."""

    def __init__(self) -> None:
        self.names: Counter[str] = Counter()
        self.globals: set[str] = set()
        self.wildcard = False

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.names[node.id] += 1

    def visit_Import(self, node: ast.Import | ast.ImportFrom) -> None:
        for alias in node.names:
            self.names[alias.asname or alias.name.split(".")[0]] += 1
            self.wildcard |= alias.name == "*"

    visit_ImportFrom = visit_Import

    def visit_Global(self, node: ast.Global) -> None:
        self.globals.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        # A nonlocal name refers to a function local, never a module variable.
        self.names.update(node.names)

    def visit_FunctionDef(self, node: Function | ast.ClassDef) -> None:
        if not isinstance(node, ast.Lambda):
            self.names[node.name] += 1
        for value in outer_expressions(node):
            self.visit(value)

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_ClassDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.names[node.name] += 1
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs | ast.MatchStar) -> None:
        if node.name:
            self.names[node.name] += 1
        self.generic_visit(node)

    visit_MatchStar = visit_MatchAs

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest:
            self.names[node.rest] += 1
        self.generic_visit(node)

    def visit_ListComp(self, node: Comprehension) -> None:
        # Iteration targets belong to the comprehension. Walruses in its
        # expressions bind in this namespace, so still visit those expressions.
        for generator in node.generators:
            self.visit(generator.iter)
            for condition in generator.ifs:
                self.visit(condition)
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        else:
            self.visit(node.elt)

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp


class RootLoggerVisitor(ast.NodeVisitor):
    """Find uses of simply assigned module-level root loggers."""

    def __init__(self, logger_methods: frozenset[str]) -> None:
        self.errors: list[tuple[int, int]] = []
        self.methods = logger_methods
        self.roots: dict[str, tuple[int, int]] = {}
        self.scopes: list[tuple[ast.AST, Bindings]] = []

    def visit_Module(self, node: ast.Module) -> None:
        bindings = Bindings()
        bindings.visit(node)
        modules: set[str] = set()
        factories: set[str] = set()
        for statement in node.body:
            if isinstance(statement, (ast.Import, ast.ImportFrom)):
                for alias in statement.names:
                    name = alias.asname or alias.name
                    if bindings.names[name] != 1:
                        continue
                    if isinstance(statement, ast.Import) and alias.name == "logging":
                        modules.add(name)
                    elif (
                        isinstance(statement, ast.ImportFrom)
                        and statement.level == 0
                        and statement.module == "logging"
                        and alias.name == "getLogger"
                    ):
                        factories.add(name)
            elif isinstance(statement, (ast.Assign, ast.AnnAssign)):
                value = statement.value
                if not isinstance(value, ast.Call) or value.args or value.keywords:
                    continue
                func = value.func
                if not (
                    isinstance(func, ast.Name)
                    and func.id in factories
                    or isinstance(func, ast.Attribute)
                    and func.attr == "getLogger"
                    and isinstance(func.value, ast.Name)
                    and func.value.id in modules
                ):
                    continue
                targets = (
                    statement.targets
                    if isinstance(statement, ast.Assign)
                    else [statement.target]
                )
                for target in targets:
                    if (
                        isinstance(target, ast.Name)
                        and bindings.names[target.id] == 1
                        and not bindings.wildcard
                    ):
                        self.roots[target.id] = (statement.lineno, statement.col_offset)
        self.generic_visit(node)

    def visible(self, name: str) -> bool:
        for depth, (node, bindings) in enumerate(reversed(self.scopes)):
            if name in {
                parameter.name for parameter in getattr(node, "type_params", ())
            }:
                return False
            if depth and isinstance(node, ast.ClassDef):
                # Methods and comprehensions do not inherit class attributes.
                if name == "__class__":
                    return False
                continue
            if bindings.wildcard:
                return False
            if name in bindings.globals:
                return not bindings.names[name]
            if bindings.names[name]:
                return False
        return True

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr in self.methods
            and isinstance(func.value, ast.Name)
            and func.value.id in self.roots
            and (node.lineno, node.col_offset) > self.roots[func.value.id]
            and self.visible(func.value.id)
        ):
            self.errors.append((node.lineno, node.col_offset))
        self.generic_visit(node)

    def in_scope(self, node: ast.AST, body: list[ast.AST], names: list[str]) -> None:
        bindings = Bindings()
        bindings.names.update(names)
        for child in body:
            bindings.visit(child)
        self.scopes.append((node, bindings))
        for child in body:
            self.visit(child)
        self.scopes.pop()

    def visit_FunctionDef(self, node: Function) -> None:
        for value in outer_expressions(node):
            self.visit(value)
        args = node.args
        names = [
            arg.arg
            for arg in (
                *args.posonlyargs,
                *args.args,
                *args.kwonlyargs,
                args.vararg,
                args.kwarg,
            )
            if arg is not None
        ]
        body: list[ast.AST] = (
            [node.body] if isinstance(node, ast.Lambda) else list(node.body)
        )
        self.in_scope(node, body, names)

    visit_AsyncFunctionDef = visit_FunctionDef
    visit_Lambda = visit_FunctionDef

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        for value in outer_expressions(node):
            self.visit(value)
        self.in_scope(node, list(node.body), [])

    def visit_ListComp(self, node: Comprehension) -> None:
        self.visit(node.generators[0].iter)
        targets = Bindings()
        body: list[ast.AST] = []
        for index, generator in enumerate(node.generators):
            targets.visit(generator.target)
            if index:
                body.append(generator.iter)
            body.extend(generator.ifs)
        if isinstance(node, ast.DictComp):
            body.extend((node.key, node.value))
        else:
            body.append(node.elt)
        self.in_scope(node, body, list(targets.names))

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp
