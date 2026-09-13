from __future__ import annotations

import ast
import sys
from textwrap import dedent

import pytest

from flake8_logging import Plugin


def check(source: str) -> None:
    source = dedent(source)
    expected = {
        line for line, text in enumerate(source.splitlines(), 1) if "# LOG016" in text
    }
    actual = {
        line
        for line, _, message, _ in Plugin(ast.parse(source)).run()
        if message.startswith("LOG016 ")
    }
    assert actual == expected


@pytest.mark.parametrize(
    "source",
    [
        """\
        import logging
        def outer():
            logger = logging.getLogger()
            def inner():
                logger.info("Hello")  # LOG016
            return inner
        """,
        """\
        import logging
        def outer():
            def inner():
                logger.info("Hello")  # LOG016
            logger = logging.getLogger()
            return inner
        """,
        """\
        import logging
        def outer():
            logger = logging.getLogger()
            def middle():
                async def inner():
                    logger.info("Hello")  # LOG016
                return inner
            return middle
        """,
        """\
        import logging
        def outer():
            logger = logging.getLogger()
            class Worker:
                logger.info("Class body")  # LOG016
                def work(self):
                    logger.info("Method")  # LOG016
            return Worker
        """,
        """\
        import logging
        logger = logging.getLogger()
        if enabled:
            def work():
                logger.info("Function")  # LOG016
            class Worker:
                logger.info("Class body")  # LOG016
                def work(self):
                    logger.info("Method")  # LOG016
        """,
        """\
        import logging
        logger = logging.getLogger()
        try:
            def work():
                logger.info("Function")  # LOG016
        except Exception:
            class Worker:
                def work(self):
                    logger.info("Method")  # LOG016
        """,
        """\
        import logging
        logger = logging.getLogger()
        for item in items:
            def work():
                logger.info("Function")  # LOG016
        """,
        """\
        import logging
        def outer():
            logger = logging.getLogger()
            if enabled:
                callback = lambda: logger.info("Lambda")  # LOG016
            return callback
        """,
        """\
        import logging
        logger = logging.getLogger()
        callback = lambda: logger.info("Lambda")  # LOG016
        class Worker:
            callback = lambda self: logger.info("Method lambda")  # LOG016
        """,
        """\
        import logging
        logger = logging.getLogger()
        [logger.info(item) for item in items]  # LOG016
        {logger.info(item) for item in items}  # LOG016
        {item: logger.info(item) for item in items}  # LOG016
        (logger.info(item) for item in items)  # LOG016
        """,
        """\
        import logging
        def outer():
            logger = logging.getLogger()
            return [lambda: logger.info("Closure") for item in items]  # LOG016
        """,
        """\
        import logging
        def work():
            logger = logging.getLogger()
            [logger.info(item) for item in items]  # LOG016
            logger = named_logger
        """,
        """\
        import logging
        logger = logging.getLogger()
        class Worker:
            logger = named_logger
            [logger.info(item) for item in items]  # LOG016
            callback = lambda: logger.info("Global")  # LOG016
        """,
        """\
        import logging
        logger = logging.getLogger()
        class Worker:
            logger.info("Before class assignment")  # LOG016
            logger = named_logger
            logger.info("Class attribute")
            def work(self):
                logger.info("Global")  # LOG016
        """,
        """\
        import logging
        logger = named_logger
        def outer():
            logger = logging.getLogger()
            class Worker:
                logger.info("Unbound class local uses global")
                logger = another_logger
                def work(self):
                    logger.info("Closure skips class attribute")  # LOG016
        """,
        """\
        import logging
        logger = logging.getLogger()
        class Outer:
            logger = named_logger
            class Inner:
                logger.info("Skips enclosing class")  # LOG016
        """,
        """\
        import logging
        logger = logging.getLogger()
        class Worker:
            logger = named_logger
            del logger
            logger.info("Falls back to global")  # LOG016
        """,
        """\
        import logging
        logger = logging.getLogger()
        def work():
            global logger
            logger.info("Global read")  # LOG016
        """,
        """\
        import logging
        def outer():
            logger = logging.getLogger()
            def inner():
                nonlocal logger
                logger.info("Nonlocal read")  # LOG016
        """,
        """\
        import logging
        logger = logging.getLogger()
        class Worker:
            global logger
            logger.info("Immediate global read")  # LOG016
        """,
        """\
        import logging
        def outer():
            logger = logging.getLogger()
            class Worker:
                nonlocal logger
                logger.info("Immediate nonlocal read")  # LOG016
        """,
        """\
        import logging
        def work():
            global logger
            logger = logging.getLogger()
            logger.info("Explicit assignment here")  # LOG016
        """,
        """\
        import logging
        def outer():
            logger = named_logger
            def inner():
                nonlocal logger
                logger = logging.getLogger()
                logger.info("Explicit assignment here")  # LOG016
        """,
        """\
        import logging
        def work():
            logger = logging.getLogger()
            if ready:
                logger.info("Branch")  # LOG016
            else:
                logger.warning("Else")  # LOG016
            for item in items:
                logger.info(item)  # LOG016
            while ready:
                logger.info("Loop")  # LOG016
                break
            with context():
                logger.info("With")  # LOG016
            try:
                perform()
            except Exception:
                logger.exception("Handler")  # LOG016
            finally:
                logger.info("Finally")  # LOG016
        """,
        """\
        import logging
        async def work():
            logger = logging.getLogger()
            async for item in items:
                logger.info(item)  # LOG016
                continue
            async with context():
                logger.info("Async with")  # LOG016
            return [logger.info(item) async for item in items]  # LOG016
        """,
        """\
        import logging
        def work():
            if enabled:
                logger = logging.getLogger()
                logger.info("Definite inside branch")  # LOG016
            else:
                logger = named_logger
            logger.info("Uncertain after join")
        """,
        """\
        import logging
        def work():
            if enabled:
                logger = logging.getLogger()
            else:
                logger = logging.getLogger()
            logger.info("Both paths root")  # LOG016
        """,
        """\
        import logging
        logger = logging.getLogger()
        for item in items:
            local = logging.getLogger()
            local.info("Local within iteration")  # LOG016
        local.info("May be unbound")
        """,
        """\
        import logging
        def work():
            logger = logging.getLogger()
            match value:
                case {"value": result} if logger.info("Guard"):  # LOG016
                    logger.info(result)  # LOG016
                case _:
                    logger.info("Fallback")  # LOG016
        """,
        """\
        import logging
        logger = logging.getLogger()
        [item for item in logger.info("Outermost iterable")]  # LOG016
        [logger.info("Element") for item in items if logger.warning("Filter")]  # LOG016
        [logger.info("Nested element") for item in items for other in logger.info("Inner iterable")]  # LOG016
        """,
        """\
        import logging
        logger = logging.getLogger()
        [logger.info("Shadowed") for logger in logger.info("Outer iterable")]  # LOG016
        logger.info("Target did not leak")  # LOG016
        """,
        """\
        import logging
        def work():
            logger = logging.getLogger()
            (alias := logger).info("Walrus receiver")  # LOG016
            alias.info("Alias")  # LOG016
            emit = alias.info
            emit("Bound method")  # LOG016
            logging.getLogger().info("Direct receiver")  # LOG016
        """,
        """\
        import logging
        logger = logging.getLogger()
        @decorate(logger.info("Decorator argument"))  # LOG016
        def work(arg=logger.info("Default"), *, option=logger.info("Keyword default")):  # LOG016
            pass
        class Worker(base(logger.info("Base")), metaclass=meta(logger.info("Metaclass"))):  # LOG016
            pass
        """,
        """\
        import logging
        logger = logging.getLogger()
        callback = lambda arg=logger.info("Lambda default"): None  # LOG016
        """,
        """\
        import logging
        def outer():
            logger = logging.getLogger()
            def sibling(logger):
                logger.info("Parameter")
            def child():
                logger.info("Free variable")  # LOG016
            logger.info("Outer unaffected")  # LOG016
            return child
        """,
        """\
        import logging
        def outer():
            logger = logging.getLogger()
            class Sibling:
                logger = named_logger
            logger.info("Class namespace does not shadow outer")  # LOG016
            return lambda: logger.info("Closure")  # LOG016
        """,
        """\
        import logging
        def outer():
            logger: object
            logger = logging.getLogger()
            def child():
                logger.info("Single actual assignment")  # LOG016
            return child
        """,
        """\
        import logging
        def outer():
            logger = logging.getLogger()
            if done:
                return lambda: logger.info("Early return")  # LOG016
            return lambda: logger.info("Later return")  # LOG016
        """,
    ],
)
def test_supported_scopes(source):
    check(source)


@pytest.mark.parametrize(
    "source",
    [
        """\
        import logging
        def outer():
            logger = logging.getLogger()
            def inner():
                logger.info("Rebound before closure runs")
            logger = named_logger
            return inner
        """,
        """\
        import logging
        def outer():
            logger = named_logger
            def inner():
                logger.info("Multiple enclosing assignments")
            logger = logging.getLogger()
            return inner
        """,
        """\
        import logging
        def outer():
            logger = logging.getLogger()
            def inner(logger):
                return lambda: logger.info("Parameter shadows all the way down")
            return inner
        """,
        """\
        import logging
        logger = logging.getLogger()
        def outer():
            def inner():
                logger.info("Enclosing local shadows module even before assignment")
            if ready:
                logger = named_logger
            return inner
        """,
        """\
        import logging
        logger = logging.getLogger()
        callback = lambda logger: logger.info("Parameter")
        callback = lambda: ((logger := named_logger), logger.info("Local walrus"))
        """,
        """\
        import logging
        logger = logging.getLogger()
        [logger.info(item) for logger in others for item in items]
        {logger.info(item) for logger in others for item in items}
        {item: logger.info(item) for logger in others for item in items}
        (logger.info(item) for logger in others for item in items)
        """,
        """\
        import logging
        def work():
            logger = logging.getLogger()
            deferred = (logger.info(item) for item in items)
            logger = named_logger
            return deferred
        """,
        """\
        import logging
        logger = named_logger
        class Worker:
            logger = logging.getLogger()
            callback = lambda: logger.info("Uses module, not class")
            [logger.info(item) for item in items]
        """,
        """\
        import logging
        __class__ = logging.getLogger()
        class Worker:
            def work(self):
                __class__.info("Implicit class cell shadows module")
        """,
        """\
        import logging
        logger = logging.getLogger()
        def mutate():
            global logger
            logger = named_logger
        def work():
            logger.info("Module binding can change in another function")
        """,
        """\
        import logging
        def outer():
            logger = logging.getLogger()
            def mutate():
                nonlocal logger
                logger = named_logger
            def work():
                logger.info("Closure cell can change")
            return mutate, work
        """,
        """\
        import logging
        def outer():
            def child():
                logger.info("May be unbound on an early return")
            if done:
                return child
            logger = logging.getLogger()
            return child
        """,
        """\
        import logging
        def work():
            logger = logging.getLogger()
            for item in items:
                logger.info("May have been reassigned in previous iteration")
                logger = named_logger
            logger.info("Unknown iteration count")
        """,
        """\
        import logging
        def work():
            logger = logging.getLogger()
            ready and (logger := named_logger)
            logger.info("Conditional mutation")
        """,
        """\
        import logging
        def work():
            logger = logging.getLogger()
            (logger := named_logger) if ready else None
            logger.info("Conditional mutation")
        """,
        """\
        import logging
        def work():
            logger = logging.getLogger()
            [(logger := named_logger) for item in items]
            logger.info("Comprehension mutation may run")
        """,
        """\
        import logging
        def work():
            logger = logging.getLogger()
            deferred = ((logger := named_logger) for item in items)
            logger.info("Deferred mutation may run")
        """,
        """\
        import logging
        def work():
            logger = named_logger
            try:
                logger = logging.getLogger()
                perform()
            except Exception:
                logger.info("Assignment may not have completed")
            finally:
                logger.info("Uncertain on exceptional path")
        """,
        """\
        import logging
        logger = logging.getLogger()
        def work():
            try:
                perform()
            except Exception as logger:
                logger.info("Exception capture")
            logger.info("Capture deleted, local remains shadowing")
        """,
        """\
        import logging
        logger = logging.getLogger()
        def work():
            match value:
                case [*logger]:
                    logger.info("Pattern capture")
        """,
        """\
        import logging
        logger = logging.getLogger()
        def work():
            logger, *rest = pair
            logger.info("Unpacked value unknown")
            del logger
            logger.info("Deleted local")
        """,
        """\
        from .logging import getLogger
        logger = getLogger()
        logger.info("Relative import is not stdlib")
        """,
        """\
        import logging
        root = logging.getLogger()
        configure(root)
        def configure(logger):
            logger.info("Arguments are not followed between calls")
        """,
        """\
        import logging
        root = logging.getLogger()
        self.logger = root
        self.logger.info("Attributes are not tracked")
        """,
        """\
        import logging
        root = logging.getLogger()
        loggers = [root]
        loggers[0].info("Containers are not tracked")
        """,
        """\
        import logging
        root = logging.getLogger(None)
        def outer():
            return lambda: root.info("Explicit opt-in")
        """,
        """\
        import logging
        def work():
            logger = logging.getLogger()
            try:
                return logger
            finally:
                clean_up()
            logger.info("Unreachable after return")
        """,
    ],
)
def test_shadowing_and_uncertainty(source):
    check(source)


@pytest.mark.parametrize(
    "source",
    [
        """\
        import logging
        def outer():
            logger = logging.getLogger()
            def middle():
                def inner():
                    nonlocal logger
                    logger.info("Skip intervening non-owner scope")  # LOG016
            return middle
        """,
        """\
        import logging
        logger = logging.getLogger()
        def work():
            nonlocal logger
            logger.info("Invalid nonlocal must not resolve to the module")
        """,
        """\
        def work():
            nonlocal missing
            missing = unknown
            missing.info("Invalid nonlocal assignment must not resolve elsewhere")
        """,
        """\
        import logging
        logger = logging.getLogger()
        {**other, "message": logger.info("Dict unpacking")}  # LOG016
        """,
        """\
        import logging
        logger = logging.getLogger()
        def work():
            try:
                perform()
            except:
                logger.info("Bare handler")  # LOG016
        """,
        """\
        import logging
        logger = logging.getLogger()
        def work(*args, **kwargs):
            logger.info("Variadic parameters")  # LOG016
        """,
        """\
        import logging
        def work():
            logger = logging.getLogger()
            if condition:
                return logger
            else:
                raise RuntimeError()
            logger.info("Unreachable")
        """,
        """\
        import logging
        def work():
            logger = logging.getLogger()
            try:
                raise RuntimeError()
            except Exception:
                return logger
            logger.info("Unreachable")
        """,
        """\
        import logging
        def work():
            logger = logging.getLogger()
            with context() as resource:
                logger.info("With target")  # LOG016
        """,
        """\
        import logging
        def work():
            logger = logging.getLogger()
            logger.info({"message": (logger := other)})  # LOG016
            logger.info("Receiver was rebound by previous argument")
        """,
        """\
        import logging
        def work():
            logger = logging.getLogger()
            del storage[logger.info("Target expression")]  # LOG016
            storage[logger.info("Assignment target")] = value  # LOG016
        """,
    ],
)
def test_additional_binding_and_execution_cases(source):
    check(source)


@pytest.mark.skipif(
    sys.version_info < (3, 12), reason="Type parameters require Python 3.12"
)
def test_python_312_type_scopes():
    check(
        """\
        import logging
        logger = logging.getLogger()
        def work[logger]():
            logger.info("Type parameter shadows module")
        class Worker[logger]:
            logger.info("Class type parameter")
            def work(self):
                logger.info("Class type parameter visible in method")
        root = logging.getLogger()
        type root = int
        root.info("Type alias is not a logger")
        """
    )


@pytest.mark.skipif(
    sys.version_info < (3, 11), reason="Exception groups require Python 3.11"
)
def test_exception_groups():
    check(
        """\
        import logging
        logger = logging.getLogger()
        def work():
            try:
                perform()
            except* Exception as errors:
                logger.exception("Group")  # LOG016
        """
    )


def test_global_declaration_in_module_is_a_noop():
    check(
        """\
        import logging
        global logger
        logger = logging.getLogger()
        def work():
            logger.info("Global declaration at module level")  # LOG016
        """
    )
