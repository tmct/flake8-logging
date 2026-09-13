from __future__ import annotations

import ast
import logging
import re
from functools import partial
from importlib.metadata import version
from textwrap import dedent

import pytest

from flake8_logging import Plugin, flatten_str_chain


@pytest.fixture
def flake8_path(flake8_path):
    (flake8_path / "setup.cfg").write_text(
        dedent(
            """\
            [flake8]
            select = LOG
            """
        )
    )
    yield flake8_path


class TestIntegration:
    def test_version(self, flake8_path):
        result = flake8_path.run_flake8(["--version"])
        version_regex = r"flake8-logging:( )*" + version("flake8-logging")
        unwrapped = "".join(result.out_lines)
        assert re.search(version_regex, unwrapped)

    def test_log001(self, flake8_path):
        (flake8_path / "example.py").write_text(
            dedent(
                """\
                import logging
                logging.Logger("x")
                """
            )
        )

        result = flake8_path.run_flake8()

        assert result.out_lines == [
            "./example.py:2:1: LOG001 use logging.getLogger() to instantiate loggers"
        ]

    def test_log016(self, flake8_path):
        (flake8_path / "example.py").write_text(
            'import logging\nlogger = logging.getLogger()\nlogger.info("Hello")\n'
        )

        result = flake8_path.run_flake8()

        assert result.out_lines == [
            "./example.py:3:1: LOG016 avoid logging through an implicitly obtained root logger"
        ]

        result = flake8_path.run_flake8(["--extend-ignore=LOG016"])

        assert result.out_lines == []


def run(source: str, ignore: tuple[str, ...] = ()) -> list[tuple[int, int, str]]:
    tree = ast.parse(dedent(source))
    return [
        (line, col, msg)
        for (line, col, msg, type_) in Plugin(tree).run()
        if msg[:6] not in ignore
    ]


run_ignore_log015 = partial(run, ignore=("LOG015",))


class TestLOG001:
    def test_attr(self):
        results = run(
            """\
            import logging
            logging.Logger("x")
            """
        )

        assert results == [
            (2, 0, "LOG001 use logging.getLogger() to instantiate loggers")
        ]

    def test_attr_as_name(self):
        results = run(
            """\
            import logging as lm
            lm.Logger("x")
            """
        )

        assert results == [
            (2, 0, "LOG001 use logging.getLogger() to instantiate loggers")
        ]

    def test_attr_in_class_def(self):
        results = run(
            """\
            import logging
            class Maker:
                logger = logging.Logger("x")
            """
        )

        assert results == [
            (3, 13, "LOG001 use logging.getLogger() to instantiate loggers")
        ]

    def test_attr_other_module(self):
        results = run(
            """\
            import our_logging
            our_logging.Logger("x")
            """
        )

        assert results == []

    def test_direct(self):
        results = run(
            """\
            from logging import Logger
            Logger("x")
            """
        )

        assert results == [
            (2, 0, "LOG001 use logging.getLogger() to instantiate loggers")
        ]

    def test_direct_not_from_logging(self):
        results = run(
            """\
            from our_logging import Logger
            Logger("x")
            """
        )

        assert results == []

    def test_direct_aliased(self):
        results = run(
            """\
            from logging import Logger as _Logger
            _Logger("x")
            """
        )

        assert results == []

    def test_in_function_def(self):
        results = run(
            """\
            import logging
            def test_thing():
                logging.Logger("x")
            """
        )

        assert results == []

    def test_direct_in_function_def(self):
        results = run(
            """\
            from logging import Logger
            def test_thing():
                Logger("x")
            """
        )

        assert results == []

    def test_in_async_function_def(self):
        results = run(
            """\
            import logging
            async def test_thing():
                logging.Logger("x")
            """
        )

        assert results == []

    def test_direct_in_async_function_def(self):
        results = run(
            """\
            from logging import Logger
            async def test_thing():
                Logger("x")
            """
        )

        assert results == []


class TestLOG002:
    def test_attr(self):
        results = run(
            """\
            import logging
            logging.getLogger(__file__)
            """
        )

        assert results == [(2, 18, "LOG002 use __name__ with getLogger()")]

    def test_attr_cached(self):
        results = run(
            """\
            import logging
            logging.getLogger(__cached__)
            """
        )

        assert results == [(2, 18, "LOG002 use __name__ with getLogger()")]

    def test_attr_in_function_def(self):
        results = run(
            """\
            import logging
            def thing():
                logging.getLogger(__file__)
            """
        )

        assert results == [(3, 22, "LOG002 use __name__ with getLogger()")]

    def test_direct(self):
        results = run(
            """\
            from logging import getLogger
            getLogger(__file__)
            """
        )

        assert results == [(2, 10, "LOG002 use __name__ with getLogger()")]

    def test_attr_dunder_name(self):
        results = run(
            """\
            import logging
            logging.getLogger(__name__)
            """
        )

        assert results == []

    def test_attr_other_module(self):
        results = run(
            """\
            import our_logging
            our_logging.getLogger(__file__)
            """
        )

        assert results == []


class TestLOG003:
    def test_module_call(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Hi", extra={"msg": "Ho"})
            """
        )

        assert results == [
            (2, 26, "LOG003 extra key 'msg' clashes with LogRecord attribute")
        ]

    @pytest.mark.parametrize("key", logging.makeLogRecord({}).__dict__.keys())
    def test_module_call_logrecord_keys(self, key):
        results = run_ignore_log015(
            f"""\
            import logging
            logging.info("Hi", extra={{"{key}": "Ho"}})
            """
        )

        assert results == [
            (2, 26, f"LOG003 extra key '{key}' clashes with LogRecord attribute")
        ]

    @pytest.mark.parametrize("key", ["asctime", "message"])
    def test_module_call_formatter_keys(self, key):
        results = run_ignore_log015(
            f"""\
            import logging
            logging.info("Hi", extra={{"{key}": "Ho"}})
            """
        )

        assert results == [
            (2, 26, f"LOG003 extra key '{key}' clashes with LogRecord attribute")
        ]

    def test_module_call_debug(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.debug("Hi", extra={"msg": "Ho"})
            """
        )

        assert results == [
            (2, 27, "LOG003 extra key 'msg' clashes with LogRecord attribute")
        ]

    def test_module_call_args(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Hi", extra={"args": (1,)})
            """
        )

        assert results == [
            (2, 26, "LOG003 extra key 'args' clashes with LogRecord attribute")
        ]

    def test_module_call_multiline(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info(
                "Hi",
                extra={
                    "msg": "Ho",
                },
            )
            """
        )

        assert results == [
            (5, 8, "LOG003 extra key 'msg' clashes with LogRecord attribute")
        ]

    def test_module_call_multiple(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info(
                "Hi",
                extra={
                    "args": (1,),
                    "msg": "Ho",
                },
            )
            """
        )

        assert results == [
            (5, 8, "LOG003 extra key 'args' clashes with LogRecord attribute"),
            (6, 8, "LOG003 extra key 'msg' clashes with LogRecord attribute"),
        ]

    def test_module_call_no_clash(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Hi", extra={"response_msg": "Ho"})
            """
        )

        assert results == []

    def test_module_call_no_extra(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Hi")
            """
        )

        assert results == []

    def test_module_call_extra_unsupported_type(self):
        results = run_ignore_log015(
            """\
            import logging
            extra = {"msg": "Ho"}
            logging.info("Hi", extra=extra)
            """
        )

        assert results == []

    def test_module_call_in_function_def(self):
        results = run_ignore_log015(
            """\
            import logging
            def thing():
                logging.info("Hi", extra={"msg": "Ho"})
            """
        )

        assert results == [
            (3, 30, "LOG003 extra key 'msg' clashes with LogRecord attribute")
        ]

    def test_module_call_dict_constructor(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Hi", extra=dict(msg="Ho"))
            """
        )

        assert results == [
            (2, 30, "LOG003 extra key 'msg' clashes with LogRecord attribute"),
        ]

    def test_module_call_dict_constructor_unpack(self):
        results = run_ignore_log015(
            """\
            import logging
            more = {"msg": "Ho"}
            logging.info("Hi", extra=dict(**more))
            """
        )

        assert results == []

    def test_logger_call(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)
            logger.info("Hi", extra={"msg": "Ho"})
            """
        )

        assert results == [
            (3, 25, "LOG003 extra key 'msg' clashes with LogRecord attribute")
        ]

    def test_logger_call_other_name(self):
        results = run_ignore_log015(
            """\
            import logging
            log = logging.getLogger(__name__)
            log.info("Hi", extra={"msg": "Ho"})
            """
        )

        assert results == [
            (3, 22, "LOG003 extra key 'msg' clashes with LogRecord attribute")
        ]

    def test_logger_call_dict_constructor(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)
            logger.info("Hi", extra=dict(msg="Ho"))
            """
        )

        assert results == [
            (3, 29, "LOG003 extra key 'msg' clashes with LogRecord attribute")
        ]


class TestLOG004:
    def test_module_call(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.exception("Hi")
            """
        )

        assert results == [
            (2, 0, "LOG004 avoid exception() outside of exception handlers")
        ]

    def test_module_call_in_function_def(self):
        results = run_ignore_log015(
            """\
            import logging
            def thing():
                logging.exception("Hi")
            """
        )

        assert results == [
            (3, 4, "LOG004 avoid exception() outside of exception handlers")
        ]

    def test_module_call_wrapped_in_function_def(self):
        # We can’t guarantee when the function will be called…
        results = run_ignore_log015(
            """\
            import logging
            try:
                acme_api()
            except AcmeError:
                def handle():
                    logging.exception("Hi")
                handle()
            """
        )

        assert results == [
            (6, 8, "LOG004 avoid exception() outside of exception handlers")
        ]

    def test_module_call_ok(self):
        results = run_ignore_log015(
            """\
            import logging
            try:
                acme_api()
            except AcmeError:
                logging.exception("Hi")
            """
        )

        assert results == []

    def test_module_call_ok_in_function_def(self):
        results = run_ignore_log015(
            """\
            import logging
            def thing():
                try:
                    acme_api()
                except AcmeError:
                    logging.exception("Hi")
            """
        )

        assert results == []

    def test_logger_call(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)
            logger.exception("Hi")
            """
        )

        assert results == [
            (3, 0, "LOG004 avoid exception() outside of exception handlers")
        ]

    def test_logger_call_in_function_def(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)
            def thing():
                logger.exception("Hi")
            """
        )

        assert results == [
            (4, 4, "LOG004 avoid exception() outside of exception handlers")
        ]

    def test_logger_call_ok(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)
            try:
                acme_api()
            except AcmeError:
                logger.exception("Hi")
            """
        )

        assert results == []


class TestLOG005:
    def test_module_call_with_exc_info(self):
        results = run_ignore_log015(
            """\
            import logging
            try:
                int(x)
            except ValueError as exc:
                logging.error("Bad int", exc_info=exc)
            """
        )

        assert results == [
            (5, 4, "LOG005 use exception() within an exception handler"),
        ]

    def test_module_call_with_exc_info_true(self):
        results = run_ignore_log015(
            """\
            import logging
            try:
                int(x)
            except ValueError as exc:
                logging.error("Bad int", exc_info=True)
            """
        )

        assert results == [
            (5, 4, "LOG005 use exception() within an exception handler"),
        ]

    def test_module_call_with_exc_info_1(self):
        results = run_ignore_log015(
            """\
            import logging
            try:
                int(x)
            except ValueError as exc:
                logging.error("Bad int", exc_info=1)
            """
        )

        assert results == [
            (5, 4, "LOG005 use exception() within an exception handler"),
        ]

    def test_module_call_with_exc_info_string(self):
        results = run_ignore_log015(
            """\
            import logging
            try:
                int(x)
            except ValueError as exc:
                logging.error("Bad int", exc_info="yes")
            """
        )

        assert results == [
            (5, 4, "LOG005 use exception() within an exception handler"),
        ]

    def test_module_call_without_exc_info(self):
        results = run_ignore_log015(
            """\
            import logging
            try:
                int(x)
            except ValueError:
                logging.error("Bad int")
            """
        )

        assert results == [
            (5, 4, "LOG005 use exception() within an exception handler"),
        ]

    def test_module_call_with_false_exc_info(self):
        results = run_ignore_log015(
            """\
            import logging
            try:
                int(x)
            except ValueError:
                logging.error("Bad int", exc_info=False)
            """
        )

        assert results == []

    def test_module_call_with_alternative_exc_info(self):
        results = run_ignore_log015(
            """\
            import logging
            try:
                int(x)
            except ValueError as exc:
                exc2 = AttributeError("Bad int")
                logging.error("Bad int", exc_info=exc2)
            """
        )

        assert results == []

    def test_logger_call_with_exc_info(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)
            try:
                int(x)
            except ValueError as exc:
                logger.error("Bad int", exc_info=exc)
            """
        )

        assert results == [
            (6, 4, "LOG005 use exception() within an exception handler"),
        ]

    def test_logger_call_with_exc_info_true(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)
            try:
                int(x)
            except ValueError as exc:
                logging.error("Bad int", exc_info=True)
            """
        )

        assert results == [
            (6, 4, "LOG005 use exception() within an exception handler"),
        ]


class TestLOG006:
    def test_module_call_with_true(self):
        results = run_ignore_log015(
            """\
            import logging
            try:
                1/0
            except ZeroDivisionError:
                logging.exception("Oops", exc_info=True)
            """
        )

        assert results == [
            (5, 30, "LOG006 redundant exc_info argument for exception()"),
        ]

    def test_module_call_with_exc(self):
        results = run_ignore_log015(
            """\
            import logging
            try:
                1/0
            except ZeroDivisionError as exc:
                logging.exception("Oops", exc_info=exc)
            """
        )

        assert results == [
            (5, 30, "LOG006 redundant exc_info argument for exception()"),
        ]

    def test_module_call_with_different_exc(self):
        results = run_ignore_log015(
            """\
            import logging
            try:
                1/0
            except ZeroDivisionError as exc:
                exc2 = AttributeError("?")
                logging.exception("Oops", exc_info=exc2)
            """
        )

        assert results == []

    def test_logger_call_with_true(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)
            try:
                1/0
            except ZeroDivisionError:
                logger.exception("Oops", exc_info=True)
            """
        )

        assert results == [
            (6, 29, "LOG006 redundant exc_info argument for exception()"),
        ]

    def test_logger_call_with_exc(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)
            try:
                1/0
            except ZeroDivisionError as exc:
                logger.exception("Oops", exc_info=exc)
            """
        )

        assert results == [
            (6, 29, "LOG006 redundant exc_info argument for exception()"),
        ]


class TestLOG007:
    def test_module_call_with_false(self):
        results = run_ignore_log015(
            """\
            import logging
            try:
                1/0
            except ZeroDivisionError:
                logging.exception("Oops", exc_info=False)
            """
        )

        assert results == [
            (5, 30, "LOG007 use error() instead of exception() with exc_info=False"),
        ]

    def test_module_call_with_0(self):
        results = run_ignore_log015(
            """\
            import logging
            try:
                1/0
            except ZeroDivisionError:
                logging.exception("Oops", exc_info=0)
            """
        )

        assert results == [
            (5, 30, "LOG007 use error() instead of exception() with exc_info=False"),
        ]

    def test_logger_call_with_false(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)
            try:
                1/0
            except ZeroDivisionError:
                logger.exception("Oops", exc_info=False)
            """
        )

        assert results == [
            (6, 29, "LOG007 use error() instead of exception() with exc_info=False"),
        ]


class TestLOG008:
    def test_module_call(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.warn("Squawk")
            """
        )

        assert results == [
            (2, 0, "LOG008 warn() is deprecated, use warning() instead"),
        ]

    def test_logger_call(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)
            logger.warn("Squawk")
            """
        )

        assert results == [
            (3, 0, "LOG008 warn() is deprecated, use warning() instead"),
        ]


class TestLOG009:
    def test_access(self):
        results = run(
            """\
            import logging
            logging.WARN
            """
        )

        assert results == [
            (2, 0, "LOG009 WARN is undocumented, use WARNING instead"),
        ]

    def test_access_alias(self):
        results = run(
            """\
            import logging as log
            log.WARN
            """
        )

        assert results == [
            (2, 0, "LOG009 WARN is undocumented, use WARNING instead"),
        ]

    def test_import(self):
        results = run(
            """\
            from logging import WARN
            """
        )

        assert results == [
            (1, 20, "LOG009 WARN is undocumented, use WARNING instead"),
        ]

    def test_import_multiline(self):
        results = run(
            """\
            from logging import (
                WARN,
            )
            """
        )

        assert results == [
            (2, 4, "LOG009 WARN is undocumented, use WARNING instead"),
        ]

    def test_import_alias(self):
        results = run(
            """\
            from logging import WARN as whatev
            """
        )

        assert results == [
            (1, 20, "LOG009 WARN is undocumented, use WARNING instead"),
        ]


class TestLOG010:
    def test_module_call(self):
        results = run_ignore_log015(
            """\
            import logging

            try:
                ...
            except Exception as exc:
                logging.exception(exc)
            """
        )

        assert results == [
            (6, 22, "LOG010 exception() does not take an exception"),
        ]

    def test_module_call_multiline(self):
        results = run_ignore_log015(
            """\
            import logging

            try:
                ...
            except Exception as exc:
                logging.exception(
                    exc,
                )
            """
        )

        assert results == [
            (7, 8, "LOG010 exception() does not take an exception"),
        ]

    def test_module_call_no_args(self):
        results = run_ignore_log015(
            """\
            import logging

            try:
                ...
            except Exception as exc:
                logging.exception()
            """
        )

        assert results == []

    def test_module_call_second_arg(self):
        results = run_ignore_log015(
            """\
            import logging

            try:
                ...
            except Exception as exc:
                logging.exception("Saw %s", exc)
            """
        )

        assert results == []

    def test_module_call_not_exc_handler_name(self):
        results = run_ignore_log015(
            """\
            import logging

            try:
                ...
            except Exception:
                exc = "Uh-oh"
                logging.exception(exc)
            """
        )

        assert results == []

    def test_module_call_in_function_def(self):
        results = run_ignore_log015(
            """\
            import logging

            try:
                ...
            except Exception as exc:
                def later():
                    exc = "message"
                    logging.exception(exc)
            """
        )

        assert results == [
            (8, 8, "LOG004 avoid exception() outside of exception handlers")
        ]

    def test_logger_call(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)

            try:
                ...
            except Exception as exc:
                logger.exception(exc)
            """
        )

        assert results == [
            (7, 21, "LOG010 exception() does not take an exception"),
        ]


class TestLOG011:
    def test_module_call(self):
        results = run_ignore_log015(
            """\
            import logging

            logging.info(f"Hi {name}")
            """
        )

        assert results == [
            (3, 13, "LOG011 avoid pre-formatting log messages"),
        ]

    def test_module_call_multiline(self):
        results = run_ignore_log015(
            """\
            import logging

            logging.info(
                f"Hi {name}"
            )
            """
        )

        assert results == [
            (4, 4, "LOG011 avoid pre-formatting log messages"),
        ]

    def test_module_call_log(self):
        results = run_ignore_log015(
            """\
            import logging

            logging.log(
                logging.INFO,
                f"Hi {name}",
            )
            """
        )

        assert results == [
            (5, 4, "LOG011 avoid pre-formatting log messages"),
        ]

    def test_module_call_str_format(self):
        results = run_ignore_log015(
            """\
            import logging

            logging.info("Hi {}".format(name))
            """
        )

        assert results == [
            (3, 13, "LOG011 avoid pre-formatting log messages"),
        ]

    def test_module_call_str_doormat(self):
        results = run_ignore_log015(
            """\
            import logging

            logging.info("Hi {}".doormat(name))
            """
        )

        assert results == []

    def test_module_call_mod_format(self):
        results = run_ignore_log015(
            """\
            import logging

            logging.info("Hi %s" % (name,))
            """
        )

        assert results == [
            (3, 13, "LOG011 avoid pre-formatting log messages"),
        ]

    def test_module_call_concatenation(self):
        results = run_ignore_log015(
            """\
            import logging

            logging.info("Hi " + name + "!")
            """
        )

        assert results == [
            (3, 13, "LOG011 avoid pre-formatting log messages"),
        ]

    def test_module_call_concatenation_multiple(self):
        results = run_ignore_log015(
            """\
            import logging

            logging.info("Hi " + name)
            """
        )

        assert results == [
            (3, 13, "LOG011 avoid pre-formatting log messages"),
        ]

    def test_module_call_concatenation_non_string(self):
        results = run_ignore_log015(
            """\
            import logging

            logging.info("Hi " + 1)
            """
        )

        assert results == [
            (3, 13, "LOG011 avoid pre-formatting log messages"),
        ]

    def test_module_call_concatenation_f_string(self):
        results = run_ignore_log015(
            """\
            import logging

            logging.info(f"Hi" "a")
            """
        )

        assert results == [
            (3, 13, "LOG011 avoid pre-formatting log messages"),
        ]

    def test_module_call_concatenation_all_strings(self):
        results = run_ignore_log015(
            """\
            import logging

            logging.info("Hi " + "name")
            """
        )

        assert results == []

    def test_module_call_non_addition(self):
        results = run_ignore_log015(
            """\
            import logging

            logging.info("not" - "valid")
            """
        )

        assert results == []

    def test_module_call_keyword(self):
        results = run_ignore_log015(
            """\
            import logging

            logging.info(msg=f"Hi {name}")
            """
        )

        assert results == [
            (3, 17, "LOG011 avoid pre-formatting log messages"),
        ]

    def test_logger_call(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)

            logger.info(f"Hi {name}")
            """
        )

        assert results == [
            (4, 12, "LOG011 avoid pre-formatting log messages"),
        ]

    def test_logger_call_str_format(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)

            logger.info("Hi {name}".format(name=name))
            """
        )

        assert results == [
            (4, 12, "LOG011 avoid pre-formatting log messages"),
        ]

    def test_logger_call_mod_format(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)

            logger.info("Hi %(name)s" % {"name": name})
            """
        )

        assert results == [
            (4, 12, "LOG011 avoid pre-formatting log messages"),
        ]

    def test_logger_call_concatenation(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)

            logger.info("Hi " + name)
            """
        )

        assert results == [
            (4, 12, "LOG011 avoid pre-formatting log messages"),
        ]

    def test_logger_call_concatenation_multiple(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)

            logger.info("Hi " + name + "!")
            """
        )

        assert results == [
            (4, 12, "LOG011 avoid pre-formatting log messages"),
        ]

    def test_logger_call_concatenation_all_strings(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)

            logger.info("Hi " + "name" + "!")
            """
        )

        assert results == []

    def test_logger_call_keyword(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)

            logger.info(msg=f"Hi {name}")
            """
        )

        assert results == [
            (4, 16, "LOG011 avoid pre-formatting log messages"),
        ]


class TestLOG012:
    def test_module_call_modpos_args_1_0(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Blending %s")
            """
        )

        assert results == [
            (2, 13, "LOG012 formatting error: 1 % placeholder but 0 arguments"),
        ]

    def test_module_call_modpos_args_2_0(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Blending %s %s")
            """
        )

        assert results == [
            (2, 13, "LOG012 formatting error: 2 % placeholders but 0 arguments"),
        ]

    def test_module_call_modpos_args_0_1(self):
        # Presume another style is in use
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Blending", fruit)
            """
        )

        assert results == []

    def test_module_call_modpos_args_0_percent(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Blending 100%%")
            """
        )

        assert results == []

    def test_module_call_modpos_args_1_percent(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Blended %s%% of %s", percent, fruit)
            """
        )

        assert results == []

    def test_module_call_modpos_args_2_1_minwidth(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Blending %*d", fruit)
            """
        )

        assert results == [
            (2, 13, "LOG012 formatting error: 2 % placeholders but 1 argument"),
        ]

    def test_module_call_modpos_args_2_1_precision(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Blending %.*d", fruit)
            """
        )

        assert results == [
            (2, 13, "LOG012 formatting error: 2 % placeholders but 1 argument"),
        ]

    def test_module_call_modpos_args_3_1_minwidth_precision(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Blending %*.*f", fruit)
            """
        )

        assert results == [
            (2, 13, "LOG012 formatting error: 3 % placeholders but 1 argument"),
        ]

    def test_module_call_modpos_joined_args_1_0(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Blending " + "%s")
            """
        )

        assert results == [
            (2, 13, "LOG012 formatting error: 1 % placeholder but 0 arguments"),
        ]

    def test_module_call_log_modpos_args_1_0(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.log(logging.INFO, "Blending %s")
            """
        )

        assert results == [
            (2, 26, "LOG012 formatting error: 1 % placeholder but 0 arguments"),
        ]

    def test_module_call_modpos_kwarg(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info(msg="Blending %s")
            """
        )

        assert results == []

    def test_module_call_log_modpos_kwarg(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.log(logging.INFO, msg="Blending %s")
            """
        )

        assert results == []

    def test_module_call_modpos_star_args(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Blending %s %s", *args)
            """
        )

        assert results == []

    def test_module_call_named(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Blending %(fruit)s")
            """
        )

        assert results == []

    def test_module_call_strformat(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Blending {}")
            """
        )

        assert results == []

    def test_module_call_template(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Blending $fruit")
            """
        )

        assert results == []

    def test_attr_call_modpos_args_1_0(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)
            logger.info("Blending %s")
            """
        )

        assert results == [
            (3, 12, "LOG012 formatting error: 1 % placeholder but 0 arguments"),
        ]

    def test_attr_call_modpos_joined_args_1_0(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)
            logger.info("Blending" + " " + "%s")
            """
        )

        assert results == [
            (3, 12, "LOG012 formatting error: 1 % placeholder but 0 arguments"),
        ]


class TestLOG013:
    def test_module_call_missing(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Blending %(fruit)s", {})
            """
        )

        assert results == [
            (2, 13, "LOG013 formatting error: missing key: 'fruit'"),
        ]

    def test_module_call_unreferenced(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Blending %(fruit)s", {"fruit": fruit, "colour": "yellow"})
            """
        )

        assert results == [
            (2, 35, "LOG013 formatting error: unreferenced key: 'colour'"),
        ]

    def test_module_call_log_missing(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.log(logging.INFO, "Blending %(fruit)s", {})
            """
        )

        assert results == [
            (2, 26, "LOG013 formatting error: missing key: 'fruit'"),
        ]

    def test_module_call_log_unreferenced(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.log(
                logging.INFO,
                "Blending %(fruit)s",
                {"fruit": fruit, "colour": "yellow"},
            )
            """
        )

        assert results == [
            (5, 4, "LOG013 formatting error: unreferenced key: 'colour'"),
        ]

    def test_module_call_all_args(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Blending %(fruit)s", {"fruit": fruit})
            """
        )

        assert results == []

    def test_module_call_kwarg_all_args(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info({"fruit": fruit}, msg="Blending %(fruit)s")
            """
        )

        assert results == []

    def test_module_call_log_kwarg(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.log(logging.INFO, {"fruit": fruit}, msg="Blending %(fruit)s")
            """
        )

        assert results == []

    def test_attr_call_missing(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)
            logger.info("Blending %(fruit)s", {})
            """
        )

        assert results == [
            (3, 12, "LOG013 formatting error: missing key: 'fruit'"),
        ]

    def test_attr_call_unreferenced(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)
            logger.info("Blending %(fruit)s", {"fruit": fruit, "colour": "yellow"})
            """
        )

        assert results == [
            (3, 34, "LOG013 formatting error: unreferenced key: 'colour'"),
        ]

    def test_attr_call_log_missing(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)
            logger.log(logging.INFO, "Blending %(fruit)s", {})
            """
        )

        assert results == [
            (3, 25, "LOG013 formatting error: missing key: 'fruit'"),
        ]

    def test_attr_call_log_unreferenced(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)
            logger.log(
                logging.INFO,
                "Blending %(fruit)s",
                {"fruit": fruit, "colour": "yellow"},
            )
            """
        )

        assert results == [
            (6, 4, "LOG013 formatting error: unreferenced key: 'colour'"),
        ]


class TestLOG014:
    def test_module_call(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Uh oh", exc_info=True)
            """
        )

        assert results == [
            (2, 22, "LOG014 avoid exc_info=True outside of exception handlers"),
        ]

    def test_module_call_truthy(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Uh oh", exc_info=1)
            """
        )

        assert results == [
            (2, 22, "LOG014 avoid exc_info=True outside of exception handlers"),
        ]

    def test_module_call_name(self):
        results = run_ignore_log015(
            """\
            import logging
            logging.info("Uh oh", exc_info=maybe)
            """
        )

        assert results == []

    def test_attr_call(self):
        results = run_ignore_log015(
            """\
            import logging
            logger = logging.getLogger(__name__)
            logger.info("Uh oh", exc_info=True)
            """
        )

        assert results == [
            (3, 21, "LOG014 avoid exc_info=True outside of exception handlers"),
        ]


class TestLOG015:
    def test_root_call(self):
        results = run(
            """\
            import logging
            logging.info(...)
            """
        )
        assert results == [
            (2, 0, "LOG015 avoid logging calls on the root logger"),
        ]

    def test_root_call_alias(self):
        results = run(
            """\
            import logging as loglog
            loglog.info(...)
            """
        )
        assert results == [
            (2, 0, "LOG015 avoid logging calls on the root logger"),
        ]

    def test_imported_function_call(self):
        results = run(
            """\
            from logging import info
            info(...)
            """
        )
        assert results == [
            (2, 0, "LOG015 avoid logging calls on the root logger"),
        ]

    def test_logger_call(self):
        results = run(
            """\
            import logging as logmod
            logging = logmod.getLogger(__name__)
            logging.info(...)
            """
        )
        assert results == []


class TestLOG016:
    @pytest.mark.parametrize(
        ("import_statement", "get_logger"),
        [
            ("import logging", "logging.getLogger"),
            ("import logging as lm", "lm.getLogger"),
            ("from logging import getLogger", "getLogger"),
        ],
    )
    def test_no_arguments(self, import_statement, get_logger):
        results = run(f"{import_statement}\nlogger = {get_logger}()\nlogger.info(...)")

        assert results == [
            (3, 0, "LOG016 avoid logging through an implicitly obtained root logger")
        ]

    @pytest.mark.parametrize(
        "arguments",
        [
            "__name__",
            "None",
            '"example"',
            "name=__name__",
            "name=None",
            "*args",
            "**kwargs",
        ],
    )
    def test_explicit_arguments(self, arguments):
        results = run(
            f"import logging\nlogger = logging.getLogger({arguments})\nlogger.info(...)"
        )

        assert results == []

    @pytest.mark.parametrize("definition", ["def", "async def"])
    def test_in_function(self, definition):
        results = run(
            f"""\
            import logging
            {definition} configure_logging():
                root_logger = logging.getLogger()
                root_logger.addHandler(handler)
                root_logger.info("Hello")
            """
        )

        assert results == [
            (5, 4, "LOG016 avoid logging through an implicitly obtained root logger")
        ]

    @pytest.mark.parametrize(
        "source",
        [
            "import our_logging\nour_logging.getLogger()",
            "from our_logging import getLogger\ngetLogger()",
            "getLogger()",
        ],
    )
    def test_unrelated(self, source):
        assert run(source) == []

    def test_root_call(self):
        results = run(
            """\
            import logging
            logger = logging.getLogger()
            logger.info(...)
            """
        )
        assert results == [
            (3, 0, "LOG016 avoid logging through an implicitly obtained root logger"),
        ]

    def test_root_call_alias(self):
        results = run(
            """\
            import logging as loglog
            logger = loglog.getLogger()
            logger.info(...)
            """
        )
        assert results == [
            (3, 0, "LOG016 avoid logging through an implicitly obtained root logger"),
        ]

    def test_warning_call(self):
        results = run(
            """\
            import logging
            logger = logging.getLogger()
            logger.warning(...)
            """
        )
        assert results == [
            (3, 0, "LOG016 avoid logging through an implicitly obtained root logger"),
        ]

    def test_logger_call(self):
        results = run(
            """\
            import logging
            logger = logging.getLogger(__name__)
            logger.info(...)
            """
        )
        assert results == []

    def test_logger_call_custom_name(self):
        results = run(
            """\
            import logging
            logger = logging.getLogger("my.lovely.logger")
            logger.info(...)
            """
        )
        assert results == []

    @pytest.mark.parametrize(
        "operation",
        [
            "pass",
            "root.addHandler(handler)",
            "root.removeHandler(handler)",
            "root.setLevel(logging.DEBUG)",
            "print(root.handlers)",
            "root.isEnabledFor(logging.INFO)",
        ],
    )
    def test_configuration_only(self, operation):
        assert (
            run(
                f"import logging\ndef configure():\n    root = logging.getLogger()\n    {operation}"
            )
            == []
        )

    @pytest.mark.parametrize(
        "method",
        ["debug", "info", "warn", "warning", "error", "critical", "log", "exception"],
    )
    def test_logging_methods(self, method):
        results = run(
            f"import logging\ndef work():\n    root = logging.getLogger()\n    root.{method}(...)"
        )
        assert results == [
            (4, 4, "LOG016 avoid logging through an implicitly obtained root logger")
        ]

    @pytest.mark.parametrize(
        "initialization",
        [
            "root = logging.getLogger()",
            "root: logging.Logger = logging.getLogger()",
            "root = other = logging.getLogger()",
            "original = logging.getLogger()\n    root = original",
            "get_logger = logging.getLogger\n    root = get_logger()",
        ],
    )
    def test_assignment_forms(self, initialization):
        results = run(
            f"import logging\ndef work():\n    {initialization}\n    root.info(...)"
        )
        assert results == [
            (
                4 + initialization.count("\n"),
                4,
                "LOG016 avoid logging through an implicitly obtained root logger",
            )
        ]

    def test_local_aliased_import(self):
        assert run(
            """\
            def work():
                from logging import getLogger as get_logger
                root = get_logger()
                root.info(...)
            """
        ) == [(4, 4, "LOG016 avoid logging through an implicitly obtained root logger")]

    @pytest.mark.parametrize(
        "replacement",
        [
            "root = logging.getLogger(__name__)",
            "root: object = other",
            "root, other = pair",
            "del root",
            "root += other",
            "root := other",
            "from elsewhere import root",
            "import elsewhere as root",
            "def root():\n        pass",
            "class root:\n        pass",
            "if condition:\n        root = other",
            "for root in objects:\n        pass",
            "with context() as root:\n        pass",
            "match value:\n        case {'root': root}:\n            pass",
        ],
    )
    def test_reassignment(self, replacement):
        if replacement == "root := other":
            replacement = "(root := other)"
        assert (
            run(
                f"import logging\ndef work():\n    root = logging.getLogger()\n    {replacement}\n    root.info(...)"
            )
            == []
        )

    def test_bare_annotation_preserves_binding(self):
        assert run(
            """\
            import logging
            def work():
                root = logging.getLogger()
                root: logging.Logger
                root.info(...)
            """
        ) == [(5, 4, "LOG016 avoid logging through an implicitly obtained root logger")]

    def test_alias_survives_original_reassignment(self):
        assert run(
            """\
            import logging
            def work():
                root = logging.getLogger()
                other = root
                root = logging.getLogger(__name__)
                root.info(...)
                other.info(...)
            """
        ) == [(7, 4, "LOG016 avoid logging through an implicitly obtained root logger")]

    def test_multiple_calls(self):
        assert run(
            """\
            import logging
            def work():
                root = logging.getLogger()
                root.info(...)
                root.addHandler(handler)
                root.warning(...)
            """
        ) == [
            (4, 4, "LOG016 avoid logging through an implicitly obtained root logger"),
            (6, 4, "LOG016 avoid logging through an implicitly obtained root logger"),
        ]

    def test_separate_functions(self):
        assert (
            run(
                """\
            import logging
            def configure():
                root = logging.getLogger()
                root.setLevel(logging.INFO)
            def work(root):
                root.info(...)
            """
            )
            == []
        )

    @pytest.mark.parametrize("argument", ["logging", "getLogger"])
    def test_shadowed_import(self, argument):
        factory = "logging.getLogger" if argument == "logging" else "getLogger"
        assert (
            run(
                f"import logging\nfrom logging import getLogger\ndef work({argument}):\n    root = {factory}()\n    root.info(...)"
            )
            == []
        )

    def test_later_local_binding_shadows_module_import(self):
        assert (
            run(
                """\
            import logging
            def work():
                root = logging.getLogger()
                root.info(...)
                logging = other
            """
            )
            == []
        )

    def test_nested_function_does_not_inherit_root(self):
        assert run(
            """\
            import logging
            def outer():
                root = logging.getLogger()
                def inner(root):
                    root.info(...)
                root.info(...)
            """
        ) == [(6, 4, "LOG016 avoid logging through an implicitly obtained root logger")]

    @pytest.mark.parametrize(
        "expression",
        [
            "lambda root: root.info(...)",
            "[root.info(...) for root in others]",
            "(root.info(...) for root in others)",
            "{root.info(...) for root in others}",
            "{root: root.info(...) for root in others}",
        ],
    )
    def test_separate_expression_scopes(self, expression):
        assert (
            run(
                f"import logging\ndef work():\n    root = logging.getLogger()\n    {expression}"
            )
            == []
        )

    def test_conditional_assignment_is_not_definite(self):
        assert (
            run(
                """\
            import logging
            def work():
                if condition:
                    root = logging.getLogger()
                else:
                    root = other
                root.info(...)
            """
            )
            == []
        )

    def test_no_rebinding_after_conditional(self):
        assert run(
            """\
            import logging
            def work():
                root = logging.getLogger()
                if condition:
                    configure()
                root.info(...)
            """
        ) == [(6, 4, "LOG016 avoid logging through an implicitly obtained root logger")]

    def test_no_logging_after_return(self):
        assert (
            run(
                """\
            import logging
            def work():
                root = logging.getLogger()
                return root
                root.info(...)
            """
            )
            == []
        )

    def test_walrus_does_not_leave_stale_binding(self):
        assert (
            run(
                """\
            import logging
            def work():
                root = logging.getLogger()
                ((root := other), root.info(...))
            """
            )
            == []
        )

    @pytest.mark.parametrize("declaration", ["global root", "nonlocal root"])
    def test_external_binding_resolution(self, declaration):
        assert run(
            f"""\
            import logging
            def outer():
                root = logging.getLogger()
                def inner():
                    {declaration}
                    root.info(...)
            """
        ) == (
            [(6, 8, "LOG016 avoid logging through an implicitly obtained root logger")]
            if declaration == "nonlocal root"
            else []
        )

    def test_match_mapping_rebinds_root(self):
        assert (
            run(
                """\
            import logging
            def work():
                root = logging.getLogger()
                match value:
                    case {**root}:
                        pass
                root.info(...)
            """
            )
            == []
        )

    @pytest.mark.parametrize(
        "import_statement",
        ["from elsewhere import *", "if condition:\n    from elsewhere import *"],
    )
    def test_wildcard_import_invalidates_bindings(self, import_statement):
        assert (
            run(
                f"import logging\nroot = logging.getLogger()\n{import_statement}\nroot.info(...)"
            )
            == []
        )

    def test_default_expression_rebinds_outer_root(self):
        assert (
            run(
                """\
            import logging
            root = logging.getLogger()
            def work(value=(root := other)):
                pass
            root.info(...)
            """
            )
            == []
        )

    def test_function_defaults_and_decorators(self):
        assert run(
            """\
            import logging
            @decorate
            def work(value=None, *, required, option=None):
                root = logging.getLogger()
                root.info(...)
            """
        ) == [(5, 4, "LOG016 avoid logging through an implicitly obtained root logger")]


class TestLOG016ModuleBindings:
    @pytest.mark.parametrize(
        ("body", "line", "column"),
        [
            ("def work():\n    logger.info(...)", 4, 4),
            ("async def work():\n    logger.info(...)", 4, 4),
            ("class Worker:\n    def work(self):\n        logger.info(...)", 5, 8),
            (
                "class Worker:\n    async def work(self):\n        logger.info(...)",
                5,
                8,
            ),
            (
                "class Worker:\n    @staticmethod\n    def work():\n        logger.info(...)",
                6,
                8,
            ),
            (
                "class Worker:\n    @classmethod\n    def work(cls):\n        logger.info(...)",
                6,
                8,
            ),
            (
                "class Outer:\n    class Worker:\n        def work(self):\n            logger.info(...)",
                6,
                12,
            ),
        ],
    )
    def test_module_logger_used_in_deferred_body(self, body, line, column):
        results = run(f"import logging\nlogger = logging.getLogger()\n{body}")
        assert results == [
            (
                line,
                column,
                "LOG016 avoid logging through an implicitly obtained root logger",
            )
        ]

    @pytest.mark.parametrize("arguments", ["__name__", "None", "name=None"])
    def test_named_or_explicit_root_logger(self, arguments):
        results = run(
            f"""\
            import logging
            logger = logging.getLogger({arguments})
            class Worker:
                def work(self):
                    logger.info(...)
            """
        )
        assert results == []

    def test_configuration_only(self):
        results = run(
            """\
            import logging
            logger = logging.getLogger()
            class Worker:
                def configure(self, handler):
                    logger.addHandler(handler)
                    logger.setLevel(logging.INFO)
                    print(logger.handlers)
            """
        )
        assert results == []

    @pytest.mark.parametrize(
        "definition",
        [
            "def work(self, logger):\n        logger.info(...)",
            "def work(self):\n        logger = logging.getLogger(__name__)\n        logger.info(...)",
            "def work(self):\n        logger.info(...)\n        logger = other",
            "def work(self):\n        logger: object\n        logger.info(...)",
            "def work(self):\n        from elsewhere import logger\n        logger.info(...)",
            "def work(self):\n        for logger in others:\n            pass\n        logger.info(...)",
        ],
    )
    def test_method_local_shadowing(self, definition):
        results = run(
            f"import logging\nlogger = logging.getLogger()\nclass Worker:\n    {definition}"
        )
        assert results == []

    def test_class_attribute_does_not_shadow_module_name(self):
        results = run(
            """\
            import logging
            logger = logging.getLogger()
            class Worker:
                logger = logging.getLogger(__name__)
                def work(self):
                    logger.info(...)
                    self.logger.info(...)
            """
        )
        assert results == [
            (6, 8, "LOG016 avoid logging through an implicitly obtained root logger")
        ]

    def test_class_root_does_not_become_module_binding(self):
        results = run(
            """\
            import logging
            logger = logging.getLogger(__name__)
            class Worker:
                logger = logging.getLogger()
                def work(self):
                    logger.info(...)
                    self.logger.info(...)
            """
        )
        assert results == []

    def test_method_named_logger_does_not_shadow_module_name(self):
        results = run(
            """\
            import logging
            logger = logging.getLogger()
            class Worker:
                def logger(self):
                    logger.info(...)
            """
        )
        assert results == [
            (5, 8, "LOG016 avoid logging through an implicitly obtained root logger")
        ]

    def test_module_alias(self):
        results = run(
            """\
            from logging import getLogger as get_logger
            root = get_logger()
            logger = root
            class Worker:
                def work(self):
                    logger.info(...)
            """
        )
        assert results == [
            (6, 8, "LOG016 avoid logging through an implicitly obtained root logger")
        ]

    def test_sibling_methods_have_independent_locals(self):
        results = run(
            """\
            import logging
            logger = logging.getLogger()
            class Worker:
                def first(self):
                    logger = logging.getLogger(__name__)
                    logger.info(...)
                def second(self):
                    logger.info(...)
            """
        )
        assert results == [
            (8, 8, "LOG016 avoid logging through an implicitly obtained root logger")
        ]

    def test_assignment_after_class_definition(self):
        results = run(
            """\
            import logging
            class Worker:
                def work(self):
                    logger.info(...)
            logger = logging.getLogger()
            """
        )
        assert results == [
            (4, 8, "LOG016 avoid logging through an implicitly obtained root logger")
        ]

    @pytest.mark.parametrize(
        "replacement",
        [
            "logger = logging.getLogger(__name__)",
            "logger = logging.getLogger()",
            "del logger",
            "if condition:\n    logger = other",
            "def logger():\n    pass",
            "class logger:\n    pass",
            "def replace():\n    global logger\n    logger = other",
        ],
    )
    def test_module_reassignment_after_class_definition(self, replacement):
        results = run(
            f"import logging\nlogger = logging.getLogger()\nclass Worker:\n    def work(self):\n        logger.info(...)\n{replacement}"
        )
        assert results == []

    def test_module_reassignment_before_root_assignment(self):
        results = run(
            """\
            import logging
            logger = other
            def work():
                logger.info(...)
            logger = logging.getLogger()
            """
        )
        assert results == []

    def test_class_definition_expressions_invalidate_module_bindings(self):
        results = run(
            """\
            import logging
            logger = logging.getLogger()
            @decorate
            class Worker(Base, metaclass=(logger := other)):
                def work(self):
                    logger.info(...)
            """
        )
        assert results == []

    def test_function_defaults_invalidate_module_bindings(self):
        results = run(
            """\
            import logging
            logger = logging.getLogger()
            def work(value=(logger := other), *, required):
                logger.info(...)
            """
        )
        assert results == []

    def test_local_root_logger_in_method(self):
        results = run(
            """\
            import logging
            class Worker:
                def work(self):
                    logger = logging.getLogger()
                    logger.info(...)
            """
        )
        assert results == [
            (5, 8, "LOG016 avoid logging through an implicitly obtained root logger")
        ]

    def test_class_body_logging(self):
        results = run(
            """\
            import logging
            logger = logging.getLogger()
            class Worker:
                logger.info(...)
            """
        )
        assert results == [
            (4, 4, "LOG016 avoid logging through an implicitly obtained root logger")
        ]

    @pytest.mark.parametrize(
        ("body", "line", "column"),
        [
            ("if ready:\n            logger.info(...)", 6, 12),
            ("for item in items:\n            logger.info(...)", 6, 12),
            (
                "try:\n            perform()\n        except Exception:\n            logger.exception(...)",
                8,
                12,
            ),
            ("with context():\n            logger.info(...)", 6, 12),
            ("while ready:\n            logger.info(...)", 6, 12),
        ],
    )
    def test_module_logger_inside_method_control_flow(self, body, line, column):
        results = run(
            f"import logging\nlogger = logging.getLogger()\nclass Worker:\n    def work(self):\n        {body}"
        )
        assert results == [
            (
                line,
                column,
                "LOG016 avoid logging through an implicitly obtained root logger",
            )
        ]

    def test_module_logger_aliased_in_method(self):
        results = run(
            """\
            import logging
            logger = logging.getLogger()
            class Worker:
                def work(self):
                    local_logger = logger
                    local_logger.info(...)
            """
        )
        assert results == [
            (6, 8, "LOG016 avoid logging through an implicitly obtained root logger")
        ]

    def test_nested_function_can_use_stable_module_logger(self):
        results = run(
            """\
            import logging
            logger = logging.getLogger()
            def outer():
                def inner():
                    logger.info(...)
            """
        )
        assert results == [
            (5, 8, "LOG016 avoid logging through an implicitly obtained root logger")
        ]

    def test_control_flow_enters_nested_scopes(self):
        results = run(
            """\
            import logging
            logger = logging.getLogger()
            def work():
                if ready:
                    def callback():
                        logger.info(...)
                    class Inner:
                        logger.info(...)
            """
        )
        assert results == [
            (6, 12, "LOG016 avoid logging through an implicitly obtained root logger"),
            (8, 12, "LOG016 avoid logging through an implicitly obtained root logger"),
        ]

    def test_conditional_local_binding_shadows_module_logger(self):
        results = run(
            """\
            import logging
            logger = logging.getLogger()
            class Worker:
                def work(self):
                    if ready:
                        logger = other
                    logger.info(...)
            """
        )
        assert results == []


class TestFlattenStrChain:
    def run(self, source: str) -> str | None:
        tree = ast.parse(dedent(source))
        expr = tree.body[0]
        assert isinstance(expr, ast.Expr)
        return flatten_str_chain(expr.value)

    def test_single_string(self):
        result = self.run(
            """\
            "Five"
            """
        )

        assert result == "Five"

    def test_single_bytes(self):
        result = self.run(
            """\
            b"Five"
            """
        )

        assert result is None

    def test_two_added(self):
        result = self.run(
            """\
            "Five" + " "
            """
        )

        assert result == "Five "

    def test_two_str_bytes(self):
        result = self.run(
            """\
            "Five" + b" "
            """
        )

        assert result is None

    def test_two_bytes_str(self):
        result = self.run(
            """\
            b"Five" + " "
            """
        )

        assert result is None

    def test_three(self):
        result = self.run(
            """\
            "Five" + " " + "little"
            """
        )

        assert result == "Five little"

    def test_two_plus_implicit(self):
        result = self.run(
            """\
            ("Five" " ") + "little"
            """
        )

        assert result == "Five little"
