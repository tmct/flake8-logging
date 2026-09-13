from __future__ import annotations

import ast
from collections import Counter
from dataclasses import dataclass, field
from typing import Literal

Value = Literal["module", "factory", "root", "method"] | None
State = dict[str, Value]
Comprehension = ast.ListComp | ast.SetComp | ast.DictComp | ast.GeneratorExp


@dataclass(eq=False)
class Scope:
    node: ast.AST
    kind: str
    parent: Scope | None
    locals: set[str] = field(default_factory=set)
    writes: Counter[str] = field(default_factory=Counter)
    globals: set[str] = field(default_factory=set)
    nonlocals: set[str] = field(default_factory=set)
    tainted: set[str] = field(default_factory=set)
    type_parameters: set[str] = field(default_factory=set)
    wildcard: bool = False
    current: State = field(default_factory=dict)
    stable: State = field(default_factory=dict)
    exits: list[State] = field(default_factory=list)

    @property
    def deferred(self) -> bool:
        return self.kind in ("function", "generator")


def enclosing(scope: Scope) -> Scope | None:
    parent = scope.parent
    while parent is not None and parent.kind == "class":
        parent = parent.parent
    return parent


def external_owner(scope: Scope, name: str) -> Scope | None:
    parent = enclosing(scope)
    if name in scope.globals:
        while parent is not None and parent.parent is not None:
            parent = parent.parent
        return parent
    while parent is not None:
        if parent.kind != "module" and name in parent.locals:
            return parent
        parent = enclosing(parent)
    return None


class Scopes(ast.NodeVisitor):
    """Collect lexical bindings without mixing nested namespaces together."""

    def __init__(self, node: ast.Module) -> None:
        self.scope = Scope(node, "module", None)
        self.by_node: dict[ast.AST, Scope] = {node: self.scope}
        self.bindings: dict[ast.AST, tuple[Scope, str]] = {}
        self.loop_depth = 0
        self.generic_visit(node)
        for scope in self.by_node.values():
            scope.locals.difference_update(scope.globals | scope.nonlocals)
        for scope in self.by_node.values():
            for name in (scope.globals | scope.nonlocals) & scope.writes.keys():
                owner = external_owner(scope, name)
                if owner is not None:
                    owner.tainted.add(name)

    def bind(self, node: ast.AST, name: str, write: bool = True) -> None:
        self.scope.locals.add(name)
        if write:
            self.scope.writes[name] += 1 + bool(self.loop_depth)
            self.bindings[node] = (self.scope, name)

    def visit_Name(self, node: ast.Name) -> None:
        if isinstance(node.ctx, (ast.Store, ast.Del)):
            self.bind(node, node.id)

    def visit_Global(self, node: ast.Global) -> None:
        if self.scope.parent is not None:
            self.scope.globals.update(node.names)

    def visit_Nonlocal(self, node: ast.Nonlocal) -> None:
        self.scope.nonlocals.update(node.names)

    def visit_Import(self, node: ast.Import | ast.ImportFrom) -> None:
        for alias in node.names:
            if alias.name == "*":
                self.scope.wildcard = True
            else:
                self.bind(alias, alias.asname or alias.name.split(".")[0])

    visit_ImportFrom = visit_Import

    def visit_AnnAssign(self, node: ast.AnnAssign) -> None:
        if isinstance(node.target, ast.Name) and node.value is None:
            self.bind(node.target, node.target.id, write=False)
        else:
            self.visit(node.target)
        if node.value is not None:
            self.visit(node.value)

    def visit_ExceptHandler(self, node: ast.ExceptHandler) -> None:
        if node.name:
            self.bind(node, node.name)
            self.scope.writes[node.name] += 1  # The handler deletes its capture.
        self.generic_visit(node)

    def visit_MatchAs(self, node: ast.MatchAs | ast.MatchStar) -> None:
        if node.name:
            self.bind(node, node.name)
        self.generic_visit(node)

    visit_MatchStar = visit_MatchAs

    def visit_MatchMapping(self, node: ast.MatchMapping) -> None:
        if node.rest:
            self.bind(node, node.rest)
        self.generic_visit(node)

    def visit_NamedExpr(self, node: ast.NamedExpr) -> None:
        self.visit(node.value)
        outer = self.scope
        while self.scope.kind in ("comprehension", "generator"):
            assert self.scope.parent is not None
            self.scope = self.scope.parent
        self.visit(node.target)
        self.scope = outer

    def visit_For(self, node: ast.For | ast.AsyncFor | ast.While) -> None:
        self.loop_depth += 1
        self.generic_visit(node)
        self.loop_depth -= 1

    visit_AsyncFor = visit_For
    visit_While = visit_For

    def defaults(self, args: ast.arguments) -> None:
        for value in (*args.defaults, *args.kw_defaults):
            if value is not None:
                self.visit(value)

    def parameters(self, args: ast.arguments) -> None:
        for arg in (
            *args.posonlyargs,
            *args.args,
            *args.kwonlyargs,
            args.vararg,
            args.kwarg,
        ):
            if arg is not None:
                self.bind(arg, arg.arg)

    def enter(self, node: ast.AST, kind: str) -> tuple[Scope, int]:
        previous = self.scope, self.loop_depth
        self.scope = Scope(node, kind, self.scope)
        if (
            kind == "function"
            and self.scope.parent is not None
            and self.scope.parent.kind == "class"
        ):
            self.scope.locals.add("__class__")
        self.by_node[node] = self.scope
        self.loop_depth = 0
        for parameter in getattr(node, "type_params", ()):
            self.bind(parameter, parameter.name)
            self.scope.type_parameters.add(parameter.name)
        return previous

    def visit_FunctionDef(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        self.bind(node, node.name)
        for decorator in node.decorator_list:
            self.visit(decorator)
        self.defaults(node.args)
        previous = self.enter(node, "function")
        self.parameters(node.args)
        for statement in node.body:
            self.visit(statement)
        self.scope, self.loop_depth = previous

    visit_AsyncFunctionDef = visit_FunctionDef

    def visit_Lambda(self, node: ast.Lambda) -> None:
        self.defaults(node.args)
        previous = self.enter(node, "function")
        self.parameters(node.args)
        self.visit(node.body)
        self.scope, self.loop_depth = previous

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.bind(node, node.name)
        for value in (
            *node.decorator_list,
            *node.bases,
            *(k.value for k in node.keywords),
        ):
            self.visit(value)
        previous = self.enter(node, "class")
        for statement in node.body:
            self.visit(statement)
        self.scope, self.loop_depth = previous

    def visit_ListComp(self, node: Comprehension) -> None:
        self.visit(node.generators[0].iter)
        previous = self.enter(
            node, "generator" if isinstance(node, ast.GeneratorExp) else "comprehension"
        )
        self.loop_depth = 1
        for index, generator in enumerate(node.generators):
            if index:
                self.visit(generator.iter)
            self.visit(generator.target)
            for condition in generator.ifs:
                self.visit(condition)
        if isinstance(node, ast.DictComp):
            self.visit(node.key)
            self.visit(node.value)
        else:
            self.visit(node.elt)
        self.scope, self.loop_depth = previous

    visit_SetComp = visit_ListComp
    visit_DictComp = visit_ListComp
    visit_GeneratorExp = visit_ListComp


def join(states: list[State]) -> State:
    """Keep a known value only when all paths agree, including unbound paths."""
    return {
        name: states[0].get(name)
        if all(s.get(name) == states[0].get(name) for s in states)
        else None
        for name in set().union(*(state.keys() for state in states))
    }


class RootLoggerVisitor(ast.NodeVisitor):
    """Analyze lexical scopes and definite logger values within one file."""

    def __init__(self, logger_methods: frozenset[str]) -> None:
        self.errors: list[tuple[int, int]] = []
        self.methods = logger_methods
        self.pending: list[Scope] = []

    def visit_Module(self, node: ast.Module) -> None:
        self.scopes = Scopes(node)
        self.run_scope(self.scopes.by_node[node])
        # Parents finish before deferred descendants, including closures in classes.
        for scope in self.pending:
            self.run_scope(scope)
        self.errors = sorted(set(self.errors))

    def lookup(self, scope: Scope, name: str, deferred: bool = False) -> Value:
        state = scope.stable if deferred else scope.current
        if name in scope.tainted:
            return None
        if name in state:
            return state[name]
        if name in scope.globals | scope.nonlocals:
            owner = external_owner(scope, name)
            cursor: Scope | None = scope
            while cursor is not None and cursor is not owner:
                deferred = deferred or cursor.deferred
                cursor = enclosing(cursor)
            return None if owner is None else self.lookup(owner, name, deferred)
        if scope.kind != "class" and name in scope.locals:
            return None
        class_parent = scope.parent
        while class_parent is not None and class_parent.kind == "class":
            if name in class_parent.type_parameters:
                return None
            class_parent = class_parent.parent
        parent = enclosing(scope)
        if scope.kind == "class" and name in scope.locals:
            # An unbound class local falls back to globals, not an enclosing
            # function's closure cell (LOAD_NAME versus LOAD_CLASSDEREF).
            while parent is not None and parent.parent is not None:
                deferred = deferred or parent.deferred
                parent = parent.parent
        if parent is None:
            return None
        return self.lookup(parent, name, deferred or scope.deferred)

    def finish(self, scope: Scope) -> None:
        final = join([scope.current, *scope.exits])
        scope.stable = {
            name: value
            for name, value in final.items()
            if scope.writes[name] == 1
            and name not in scope.tainted | scope.globals | scope.nonlocals
            and not scope.wildcard
        }

    def run_scope(self, scope: Scope) -> None:
        node = scope.node
        scope.current.update(dict.fromkeys(scope.type_parameters))
        if isinstance(node, ast.Lambda):
            self.expr(node.body, scope)
        elif isinstance(
            node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
        ):
            for index, generator in enumerate(node.generators):
                if index:
                    self.expr(generator.iter, scope)
                self.assign(generator.target, None, scope)
                for condition in generator.ifs:
                    self.expr(condition, scope)
            if isinstance(node, ast.DictComp):
                self.expr(node.key, scope)
                self.expr(node.value, scope)
            else:
                self.expr(node.elt, scope)
        else:
            assert isinstance(
                node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
            )
            self.block(node.body, scope)
        self.finish(scope)

    def assign(
        self, target: ast.expr, value: Value, scope: Scope, delete: bool = False
    ) -> None:
        if isinstance(target, ast.Name):
            owner, name = self.scopes.bindings.get(target, (scope, target.id))
            # Comprehension walruses write to the containing scope.
            state = owner.current if owner is not scope else scope.current
            if delete:
                state.pop(name, None)
            else:
                state[name] = value
        elif isinstance(target, (ast.Tuple, ast.List)):
            for item in target.elts:
                self.assign(item, None, scope, delete)
        elif isinstance(target, ast.Starred):
            self.assign(target.value, None, scope, delete)
        else:
            self.expr(target, scope)

    def changed(self, nodes: list[ast.AST], scope: Scope) -> set[str]:
        return {
            name
            for node in nodes
            for child in ast.walk(node)
            if child in self.scopes.bindings
            for owner, name in [self.scopes.bindings[child]]
            if owner is scope
        }

    def invalidate(self, names: set[str], scope: Scope) -> None:
        for name in names:
            scope.current[name] = None

    def expr(self, node: ast.expr, scope: Scope) -> Value:
        if isinstance(node, ast.Name):
            return self.lookup(scope, node.id)
        if isinstance(node, ast.Attribute):
            value = self.expr(node.value, scope)
            if value == "module" and node.attr == "getLogger":
                return "factory"
            if value == "root" and node.attr in self.methods:
                return "method"
        elif isinstance(node, ast.Call):
            function = self.expr(node.func, scope)
            for arg in (*node.args, *(k.value for k in node.keywords)):
                self.expr(arg, scope)
            if function == "method":
                self.errors.append((node.lineno, node.col_offset))
            elif function == "factory" and not node.args and not node.keywords:
                return "root"
        elif isinstance(node, ast.NamedExpr):
            value = self.expr(node.value, scope)
            self.assign(node.target, value, scope)
            return value
        elif isinstance(node, ast.Lambda):
            self.defaults(node.args, scope)
            self.pending.append(self.scopes.by_node[node])
        elif isinstance(
            node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)
        ):
            self.expr(node.generators[0].iter, scope)
            writes = self.changed([node], scope)
            self.invalidate(writes, scope)
            child = self.scopes.by_node[node]
            if isinstance(node, ast.GeneratorExp):
                self.pending.append(child)
            else:
                self.run_scope(child)
            self.invalidate(writes, scope)  # The iterable may have been empty.
        elif isinstance(node, ast.IfExp):
            self.expr(node.test, scope)
            start = scope.current.copy()
            left = self.expr(node.body, scope)
            left_state = scope.current
            scope.current = start
            right = self.expr(node.orelse, scope)
            scope.current = join([left_state, scope.current])
            return left if left == right else None
        elif isinstance(node, ast.BoolOp):
            value = self.expr(node.values[0], scope)
            for expression in node.values[1:]:
                skipped = scope.current.copy()
                other = self.expr(expression, scope)
                scope.current = join([skipped, scope.current])
                value = value if value == other else None
            return value
        elif isinstance(node, ast.Dict):
            for key, value_node in zip(node.keys, node.values):
                if key is not None:
                    self.expr(key, scope)
                self.expr(value_node, scope)
        else:
            for child_node in ast.iter_child_nodes(node):
                if isinstance(child_node, ast.expr):
                    self.expr(child_node, scope)
        return None

    def defaults(self, args: ast.arguments, scope: Scope) -> None:
        for value in (*args.defaults, *args.kw_defaults):
            if value is not None:
                self.expr(value, scope)

    def block(self, body: list[ast.stmt], scope: Scope) -> bool:
        return any(self.statement(statement, scope) for statement in body)

    def branch(
        self, body: list[ast.stmt], scope: Scope, start: State
    ) -> tuple[State, bool]:
        scope.current = start.copy()
        stopped = self.block(body, scope)
        return scope.current, stopped

    def statement(self, node: ast.stmt, scope: Scope) -> bool:
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            for alias in node.names:
                name = alias.asname or alias.name.split(".")[0]
                value: Value = None
                if isinstance(node, ast.Import) and alias.name == "logging":
                    value = "module"
                elif (
                    isinstance(node, ast.ImportFrom)
                    and node.level == 0
                    and node.module == "logging"
                    and alias.name == "getLogger"
                ):
                    value = "factory"
                if name == "*":
                    self.invalidate(set(scope.current) | scope.locals, scope)
                else:
                    scope.current[name] = value
        elif isinstance(node, (ast.Assign, ast.AnnAssign)):
            if node.value is not None:
                value = self.expr(node.value, scope)
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                for target in targets:
                    self.assign(target, value, scope)
        elif hasattr(ast, "TypeAlias") and isinstance(node, ast.TypeAlias):
            # Alias values are lazily evaluated, not logger assignments.
            self.assign(node.name, None, scope)
        elif isinstance(node, ast.AugAssign):
            self.expr(node.target, scope)
            self.expr(node.value, scope)
            self.assign(node.target, None, scope)
        elif isinstance(node, ast.Delete):
            for target in node.targets:
                self.assign(target, None, scope, delete=True)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            for decorator in node.decorator_list:
                self.expr(decorator, scope)
            self.defaults(node.args, scope)
            self.pending.append(self.scopes.by_node[node])
            scope.current[node.name] = None
        elif isinstance(node, ast.ClassDef):
            for value_node in (
                *node.decorator_list,
                *node.bases,
                *(k.value for k in node.keywords),
            ):
                self.expr(value_node, scope)
            self.run_scope(self.scopes.by_node[node])
            scope.current[node.name] = None
        elif isinstance(node, ast.If):
            self.expr(node.test, scope)
            start = scope.current.copy()
            left, left_stop = self.branch(node.body, scope, start)
            right, right_stop = self.branch(node.orelse, scope, start)
            scope.current = join([left, right])
            return left_stop and right_stop
        elif isinstance(node, (ast.For, ast.AsyncFor, ast.While)):
            if isinstance(node, ast.While):
                expression = node.test
            else:
                expression = node.iter
            start = scope.current.copy()
            writes = self.changed([node], scope)
            self.invalidate(writes, scope)
            self.expr(expression, scope)
            if not isinstance(node, ast.While):
                self.assign(node.target, None, scope)
            self.block(node.body, scope)
            scope.current = join([start, scope.current])
            self.invalidate(writes, scope)
            self.block(node.orelse, scope)
            self.invalidate(writes, scope)
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            for item in node.items:
                self.expr(item.context_expr, scope)
                if item.optional_vars is not None:
                    self.assign(item.optional_vars, None, scope)
            return self.block(node.body, scope)
        elif isinstance(node, ast.Try) or (
            hasattr(ast, "TryStar") and isinstance(node, ast.TryStar)
        ):
            start = scope.current.copy()
            body, body_stop = self.branch(node.body, scope, start)
            if not body_stop:
                body_stop = self.block(node.orelse, scope)
            paths = [scope.current.copy()]
            stops = [body_stop]
            scope.current = start.copy()
            self.invalidate(self.changed(list(node.body), scope), scope)
            exceptional = scope.current.copy()
            for handler in node.handlers:
                scope.current = exceptional.copy()
                if handler.type is not None:
                    self.expr(handler.type, scope)
                if handler.name:
                    scope.current[handler.name] = None
                stops.append(self.block(handler.body, scope))
                if handler.name:
                    scope.current.pop(handler.name, None)
                paths.append(scope.current)
            scope.current = join(paths)
            if node.finalbody:
                scope.current = join([scope.current, exceptional, body])
                final_stop = self.block(node.finalbody, scope)
                return final_stop or all(stops)
            return all(stops)
        elif isinstance(node, ast.Match):
            self.expr(node.subject, scope)
            start = scope.current.copy()
            paths = [start]
            for case in node.cases:
                scope.current = start.copy()
                self.invalidate(self.changed([case.pattern], scope), scope)
                if case.guard is not None:
                    self.expr(case.guard, scope)
                self.block(case.body, scope)
                paths.append(scope.current)
            scope.current = join(paths)
        else:
            if isinstance(node, (ast.Expr, ast.Assert, ast.Return, ast.Raise)):
                for child in ast.iter_child_nodes(node):
                    assert isinstance(child, ast.expr)
                    self.expr(child, scope)
            if isinstance(node, (ast.Return, ast.Raise)):
                scope.exits.append(scope.current.copy())
                return True
            if isinstance(node, (ast.Break, ast.Continue)):
                return True
        return False
