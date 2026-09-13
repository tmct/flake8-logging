from __future__ import annotations

import ast
import sys
from textwrap import dedent

import pytest

from flake8_logging import Plugin

SETUP = "import logging\nlogger = logging.getLogger()\n"


def check(body: str, setup: str = SETUP) -> None:
    source = setup + dedent(body)
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
    "body",
    [
        'logger.info("Module")  # LOG016',
        'def work():\n    logger.info("Function")  # LOG016',
        'async def work():\n    logger.info("Async function")  # LOG016',
        'def outer():\n    def inner():\n        logger.info("Nested")  # LOG016',
        'class Worker:\n    logger.info("Class body")  # LOG016',
        'class Worker:\n    def work(self):\n        logger.info("Method")  # LOG016',
        'class Worker:\n    async def work(self):\n        logger.info("Async method")  # LOG016',
        'class Worker:\n    @staticmethod\n    def work():\n        logger.info("Static method")  # LOG016',
        'class Worker:\n    @classmethod\n    def work(cls):\n        logger.info("Class method")  # LOG016',
        'class Outer:\n    class Inner:\n        def work(self):\n            logger.info("Nested class")  # LOG016',
        'if ready:\n    def work():\n        logger.info("Conditional definition")  # LOG016',
        'for item in items:\n    class Worker:\n        def work(self):\n            logger.info("Loop definition")  # LOG016',
        'try:\n    perform()\nexcept Exception:\n    def work():\n        logger.info("Handler definition")  # LOG016',
        'callback = lambda: logger.info("Lambda")  # LOG016',
        'def work():\n    return lambda: logger.info("Nested lambda")  # LOG016',
        "[logger.info(item) for item in items if ready]  # LOG016",
        "{logger.info(item) for item in items}  # LOG016",
        "{item: logger.info(item) for item in items}  # LOG016",
        "(logger.info(item) for item in items)  # LOG016",
        "[logger.info(item) for batch in batches for item in batch]  # LOG016",
        "def work():\n    return [lambda: logger.info(item) for item in items]  # LOG016",
        "async def work():\n    return [logger.info(item) async for item in items]  # LOG016",
        'def work():\n    global logger\n    logger.info("Global read")  # LOG016',
        'def outer(logger):\n    def inner():\n        global logger\n        logger.info("Explicit global skips enclosing parameter")  # LOG016',
        'def work(value=logger.info("Default"), *, option=None, required):  # LOG016\n    pass',
    ],
)
def test_uses_in_different_scopes(body):
    check(body)


@pytest.mark.parametrize(
    "method",
    ["debug", "info", "warn", "warning", "error", "critical", "log", "exception"],
)
def test_logging_methods(method):
    check(f'def work():\n    logger.{method}("Message")  # LOG016')


@pytest.mark.parametrize(
    "setup",
    [
        "import logging as lm\nlogger = lm.getLogger()\n",
        "from logging import getLogger\nlogger = getLogger()\n",
        "from logging import getLogger as get_logger\nlogger = get_logger()\n",
        "import logging\nlogger: logging.Logger = logging.getLogger()\n",
        "import logging\nother = logger = logging.getLogger()\n",
    ],
)
def test_creation_forms(setup):
    check(
        'class Worker:\n    def work(self):\n        logger.info("Message")  # LOG016',
        setup,
    )


@pytest.mark.parametrize(
    "body",
    [
        'def work(logger):\n    logger.info("Parameter")',
        'def work(*logger):\n    logger.info("Parameter")',
        'def work(**logger):\n    logger.info("Parameter")',
        'def work():\n    logger = other\n    logger.info("Local")',
        'def work():\n    logger.info("Local before assignment")\n    logger = other',
        'def work():\n    logger: object\n    logger.info("Local annotation")',
        'def work():\n    del logger\n    logger.info("Deleted local")',
        'def work():\n    from elsewhere import logger\n    logger.info("Import")',
        'def work():\n    import elsewhere as logger\n    logger.info("Import alias")',
        'def work():\n    for logger in others:\n        logger.info("Loop target")',
        'def work():\n    with context() as logger:\n        logger.info("With target")',
        'def work():\n    try:\n        perform()\n    except Exception as logger:\n        logger.info("Capture")',
        'def work():\n    match value:\n        case {**logger}:\n            logger.info("Mapping capture")',
        'def work():\n    match value:\n        case [*logger]:\n            logger.info("Pattern capture")',
        'def work():\n    (logger := other)\n    logger.info("Walrus")',
        'def outer(logger):\n    def inner():\n        logger.info("Enclosing local")',
        'def outer(logger):\n    def inner():\n        nonlocal logger\n        logger.info("Nonlocal")',
        'def work():\n    global logger\n    logger = other\n    logger.info("Global assignment")',
        'callback = lambda logger: logger.info("Lambda parameter")',
        '[logger.info("Comprehension target") for logger in others]',
        '{logger.info("Comprehension target") for logger in others}',
        '{logger: logger.info("Comprehension target") for logger in others}',
        '(logger.info("Comprehension target") for logger in others)',
        'class Worker:\n    logger = other\n    logger.info("Class attribute")',
        'def work():\n    def logger():\n        pass\n    logger.info("Function binding")',
        'def work():\n    class logger:\n        pass\n    logger.info("Class binding")',
    ],
)
def test_shadowed_names(body):
    check(body + '\nlogger.info("Other scopes do not shadow module")  # LOG016')


def test_class_attributes_do_not_shadow_methods_or_comprehensions():
    check(
        """\
        class Worker:
            logger = other
            def work(self):
                logger.info("Global")  # LOG016
                self.logger.info("Attribute")
            [logger.info(item) for item in items]  # LOG016
        """
    )


def test_comprehension_iterable_and_scope():
    check(
        """\
        [logger.info("Target") for logger in logger.info("Outer iterable")]  # LOG016
        logger.info("Target did not leak")  # LOG016
        """
    )


def test_configuration_only():
    check(
        "def configure(handler):\n    logger.addHandler(handler)\n    logger.setLevel(logging.INFO)\n    print(logger.handlers)"
    )


@pytest.mark.parametrize(
    "arguments", ["__name__", "None", "name=None", "name=__name__", "*args", "**kwargs"]
)
def test_explicit_arguments(arguments):
    check(
        'def work():\n    logger.info("Message")',
        f"import logging\nlogger = logging.getLogger({arguments})\n",
    )


@pytest.mark.parametrize(
    "setup",
    [
        "logger = getLogger()\n",
        "from .logging import getLogger\nlogger = getLogger()\n",
        "import other\nlogger = other.getLogger()\n",
        "from other import getLogger\nlogger = getLogger()\n",
        "import logging\nlogging = other\nlogger = logging.getLogger()\n",
        "import logging\nlogger = logging.getLogger()\nlogger = other\n",
        "import logging\nlogger = logging.getLogger()\nif ready:\n    logger = other\n",
        "import logging\nif ready:\n    logger = logging.getLogger()\n",
        "import logging\nroot = logging.getLogger()\nlogger = root\n",
        "import logging\nlogger = logging.getLogger()\nfrom other import *\n",
        "import logging\nroot.logger = logging.getLogger()\n",
        "import logging\nlogger, other = logging.getLogger()\n",
        "import logging\nlogger: object\n",
        "import logging\nlogger = object.getLogger()\n",
    ],
)
def test_non_candidates(setup):
    check('logger.info("Unknown or reassigned")', setup)


def test_local_creation_is_out_of_scope():
    check(
        'def work():\n    logger = logging.getLogger()\n    logger.info("Local root")',
        "import logging\n",
    )


def test_calls_before_module_assignment_are_not_reported():
    check(
        'logger.info("Before assignment")\nlogger = logging.getLogger()',
        "import logging\n",
    )


def test_sibling_bindings_do_not_leak():
    check(
        'def outer():\n    def sibling(logger):\n        pass\n    logger.info("Global")  # LOG016'
    )


def test_wildcard_in_nested_scope_is_conservative():
    check('def work():\n    from other import *\n    logger.info("Unknown")')


def test_walrus_in_comprehension_binds_in_containing_function():
    check(
        'def work():\n    [(logger := other) for item in items]\n    logger.info("Local")'
    )


def test_decorators_and_class_bases():
    check(
        '@decorate(logger.info("Decorator"))  # LOG016\nclass Worker(base(logger.info("Base"))):  # LOG016\n    pass'
    )


def test_implicit_class_cell():
    check(
        'class Worker:\n    def work(self):\n        __class__.info("Class object")',
        "import logging\n__class__ = logging.getLogger()\n",
    )


@pytest.mark.skipif(
    sys.version_info < (3, 12), reason="Type parameters require Python 3.12"
)
def test_type_parameters_shadow_module_names():
    check(
        'def work[logger]():\n    logger.info("Type parameter")\nclass Worker[logger]:\n    def work(self):\n        logger.info("Class type parameter")'
    )


def test_unrelated_match_captures_do_not_shadow_logger():
    check(
        """\
        def work():
            match value:
                case {"item": item}:
                    logger.info(item)  # LOG016
                case _:
                    logger.info("Fallback")  # LOG016
        """
    )
