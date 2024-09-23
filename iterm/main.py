import datetime as dt
import itertools
import functools
import logging
import os
import platform
import re
import sys
import ssl
import shutil
import threading
import traceback
from collections import namedtuple
from time import time
from getpass import getuser

import click
import pendulum
from cli_helpers.tabular_output import TabularOutputFormatter
from cli_helpers.tabular_output.preprocessors import align_decimals, format_numbers
from cli_helpers.utils import strip_ansi
from prompt_toolkit.completion import DynamicCompleter, ThreadedCompleter
from prompt_toolkit.document import Document
from prompt_toolkit.enums import DEFAULT_BUFFER, EditingMode
from prompt_toolkit.filters import HasFocus, IsDone
from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.history import FileHistory
from prompt_toolkit.auto_suggest import AutoSuggestFromHistory
from prompt_toolkit.layout.processors import (
    ConditionalProcessor,
    HighlightMatchingBracketProcessor,
    TabsProcessor,
)
from prompt_toolkit.lexers import PygmentsLexer
from prompt_toolkit.shortcuts import CompleteStyle, PromptSession
from prompt_toolkit.input import create_input
from prompt_toolkit.keys import Keys

from iterm.utils import parse_uri

from .__init__ import __version__
from .irissession import IRISSession
from .completer import IRISCompleter
from .clitoolbar import create_toolbar_tokens_func
from .config import config_location, get_config, ensure_dir_exists
from .key_bindings import iterm_bindings
from .style import style_factory, style_factory_output
from .packages.encodingutils import utf8tounicode, text_type
from .packages import special
from .packages.special import NO_QUERY
from .packages.prompt_utils import confirm

try:
    import iris
except Exception as ex:
    print("oops", ex)
    sys.exit(1)

COLOR_CODE_REGEX = re.compile(r"\x1b(\[.*?[@-~]|\].*?(\x07|\x1b\\))")
DEFAULT_MAX_FIELD_WIDTH = 500

class iTermQuitError(Exception):
    pass


class iTerm(object):
    default_prompt = "\\u@\\N> "
    max_len_prompt = 45

    def __init__(
        self,
        quiet=False,
        logfile=None,
        itermrc=None,
        warn=None,
    ) -> None:
        self.quiet = quiet
        self.logfile = logfile
        self.irissession = None

        self.username = iris.system.Process.UserName()
        self.namespace = iris.system.Process.NameSpace()

        c = self.config = get_config(itermrc)

        self.output_file = None

        self.multi_line = c["main"].as_bool("multi_line")
        c_dest_warning = c["main"].as_bool("destructive_warning")
        self.destructive_warning = c_dest_warning if warn is None else warn

        self.min_num_menu_lines = c["main"].as_int("min_num_menu_lines")

        self.key_bindings = c["main"]["key_bindings"]
        self.syntax_style = c["main"]["syntax_style"]
        self.less_chatty = c["main"].as_bool("less_chatty")
        self.show_bottom_toolbar = c["main"].as_bool("show_bottom_toolbar")
        self.cli_style = c["colors"]
        self.style_output = style_factory_output(self.syntax_style, self.cli_style)
        self.wider_completion_menu = c["main"].as_bool("wider_completion_menu")
        self.autocompletion = c["main"].as_bool("autocompletion")
        self.login_path_as_host = c["main"].as_bool("login_path_as_host")

        self.logger = logging.getLogger(__name__)
        self.initialize_logging()

        keyword_casing = c["main"].get("keyword_casing", "auto")

        self.now = dt.datetime.today()

        self.history = []

        # Initialize completer.
        self.completer = IRISCompleter(
            keyword_casing=keyword_casing,
        )
        self._completer_lock = threading.Lock()
        self.prompt_format = c["main"].get("prompt", self.default_prompt)

        self.multiline_continuation_char = c["main"]["multiline_continuation_char"]

        self.register_special_commands()

    def quit(self):
        raise iTermQuitError

    def register_special_commands(self):
        special.register_special_command(
            self.echo_test,
            ".echo",
            "",
            "Outputs the value.",
            case_sensitive=True,
            arg_type=special.PARSED_QUERY,
        )
        special.register_special_command(
            self.change_prompt_format,
            "prompt",
            "\\R",
            "Change prompt format.",
            aliases=("\\R",),
            case_sensitive=True,
        )

    def echo_test(self, arg, **_):
        msg = arg
        if len(msg) > 1:
            msg = msg[1:-1] if msg[0] == "'" and msg[-1] == "'" else msg
            msg = msg[1:-1] if msg[0] == '"' and msg[-1] == '"' else msg
        print(msg)
        yield (None, None, None, None)

    def change_prompt_format(self, arg, **_):
        """
        Change the prompt format.
        """
        if not arg:
            message = "Missing required argument, format."
            return [(None, None, None, message)]

        self.prompt_format = self.get_prompt(arg)
        return [(None, None, None, "Changed prompt format to %s" % arg)]

    def get_prompt(self, string):
        # should be before replacing \\d
        string = string.replace("\\t", self.now.strftime("%x %X"))
        string = string.replace("\\u", self.username)
        string = string.replace("\\N", self.namespace)
        string = string.replace("\\n", "\n")
        return string

    def _build_cli(self, history):
        key_bindings = iterm_bindings(self)

        def get_message():
            prompt_format = self.prompt_format

            prompt = self.get_prompt(prompt_format)

            if (
                prompt_format == self.default_prompt
                and len(prompt) > self.max_len_prompt
            ):
                prompt = self.get_prompt("\\d> ")

            prompt = prompt.replace("\\x1b", "\x1b")
            return ANSI(prompt)

        def get_continuation(width, line_number, is_soft_wrap):
            continuation = self.multiline_continuation_char * (width - 1) + " "
            return [("class:continuation", continuation)]

        get_toolbar_tokens = create_toolbar_tokens_func(self)

        if self.wider_completion_menu:
            complete_style = CompleteStyle.MULTI_COLUMN
        else:
            complete_style = CompleteStyle.COLUMN

        with self._completer_lock:
            prompt_app = PromptSession(
                reserve_space_for_menu=self.min_num_menu_lines,
                message=get_message,
                prompt_continuation=get_continuation,
                bottom_toolbar=get_toolbar_tokens if self.show_bottom_toolbar else None,
                complete_style=complete_style,
                input_processors=[
                    # Highlight matching brackets while editing.
                    ConditionalProcessor(
                        processor=HighlightMatchingBracketProcessor(chars="[](){}"),
                        filter=HasFocus(DEFAULT_BUFFER) & ~IsDone(),
                    ),
                    # Render \t as 4 spaces instead of "^I"
                    TabsProcessor(char1=" ", char2=" "),
                ],
                auto_suggest=AutoSuggestFromHistory(),
                history=history,
                completer=ThreadedCompleter(DynamicCompleter(lambda: self.completer)),
                complete_while_typing=True,
                style=style_factory(self.syntax_style, self.cli_style),
                include_default_pygments_style=False,
                key_bindings=key_bindings,
                enable_open_in_editor=True,
                enable_system_prompt=True,
                enable_suspend=True,
                editing_mode=(
                    EditingMode.VI if self.key_bindings == "vi" else EditingMode.EMACS
                ),
                search_ignore_case=True,
            )

            return prompt_app

    def _evaluate_command(self, text):
        output = []
        return output

    def execute_command(self, text, handle_closed_connection=True):
        logger = self.logger

        self.irissession.write(text + "\n")
        while True:
            output = self.irissession.read(1)
            if not output:
                break
            print(output)

        return text

    def refresh_completions(self, history=None, persist_priorities="all"):
        """Refresh outdated completions

        :param history: A prompt_toolkit.history.FileHistory object. Used to
                        load keyword and identifier preferences

        :param persist_priorities: 'all' or 'keywords'
        """

        return

    def _on_completions_refreshed(self, new_completer, persist_priorities):
        with self._completer_lock:
            self.completer = new_completer

        if self.prompt_app:
            # After refreshing, redraw the CLI to clear the statusbar
            # "Refreshing completions..." indicator
            self.prompt_app.app.invalidate()

    def get_completions(self, text, cursor_positition):
        with self._completer_lock:
            return self.completer.get_completions(
                Document(text=text, cursor_position=cursor_positition), None
            )

    def log_output(self, output):
        """Log the output in the audit log, if it's enabled."""
        if self.logfile:
            click.echo(utf8tounicode(output), file=self.logfile)

    def echo(self, s, **kwargs):
        """Print a message to stdout.

        The message will be logged in the audit log, if enabled.

        All keyword arguments are passed to click.echo().

        """
        self.log_output(s)
        click.secho(s, **kwargs)

    def get_output_margin(self, status=None):
        """Get the output margin (number of rows for the prompt, footer and
        timing message."""
        margin = (
            self.get_reserved_space()
            + self.get_prompt(self.prompt_format).count("\n")
            + 2
        )
        if status:
            margin += 1 + status.count("\n")

        return margin

    def initialize_logging(self):
        log_file = self.config["main"]["log_file"]
        if log_file == "default":
            log_file = config_location() + "log"
        ensure_dir_exists(log_file)
        log_level = "DEBUG" or self.config["main"]["log_level"]

        # Disable logging if value is NONE by switching to a no-op handler.
        # Set log level to a high value so it doesn't even waste cycles getting called.
        if log_level.upper() == "NONE":
            handler = logging.NullHandler()
        else:
            handler = logging.FileHandler(os.path.expanduser(log_file))

        level_map = {
            "CRITICAL": logging.CRITICAL,
            "ERROR": logging.ERROR,
            "WARNING": logging.WARNING,
            "INFO": logging.INFO,
            "DEBUG": logging.DEBUG,
            "NONE": logging.CRITICAL,
        }

        log_level = level_map[log_level.upper()]

        formatter = logging.Formatter(
            "%(asctime)s (%(process)d/%(threadName)s) "
            "%(name)s %(levelname)s - %(message)s"
        )

        handler.setFormatter(formatter)

        root_logger = logging.getLogger("iterm")
        root_logger.addHandler(handler)
        root_logger.setLevel(log_level)

        root_logger.debug("Initializing iterm logging.")
        root_logger.debug("Log file %r.", log_file)

    def read_my_cnf_files(self, keys):
        """
        Reads a list of config files and merges them. The last one will win.
        :param files: list of files to read
        :param keys: list of keys to retrieve
        :returns: tuple, with None for missing keys.
        """
        cnf = self.config

        sections = ["main"]

        def get(key):
            result = None
            for sect in cnf:
                if sect in sections and key in cnf[sect]:
                    result = cnf[sect][key]
            return result

        return {x: get(x) for x in keys}

    def output(self, output, status=None):
        """Output text to stdout or a pager command.

        The status text is not outputted to pager or files.

        The message will be logged in the audit log, if enabled. The
        message will be written to the tee file, if enabled. The
        message will be written to the output file, if enabled.

        """
        if output:
            size = self.prompt_app.output.get_size()

            margin = self.get_output_margin(status)

            fits = True
            buf = []
            output_via_pager = self.explicit_pager and special.is_pager_enabled()
            for i, line in enumerate(output, 1):
                self.log_output(line)
                special.write_tee(line)
                special.write_once(line)

                if fits or output_via_pager:
                    # buffering
                    buf.append(line)
                    if len(line) > size.columns or i > (size.rows - margin):
                        fits = False
                        if not self.explicit_pager and special.is_pager_enabled():
                            # doesn't fit, use pager
                            output_via_pager = True

                        if not output_via_pager:
                            # doesn't fit, flush buffer
                            for line in buf:
                                click.secho(line)
                            buf = []
                else:
                    click.secho(line)

            if buf:
                if output_via_pager:
                    # sadly click.echo_via_pager doesn't accept generators
                    click.echo_via_pager("\n".join(buf))
                else:
                    for line in buf:
                        click.secho(line)

        if status:
            self.log_output(status)
            click.secho(status)

    def run_cli(self):
        logger = self.logger
        self.irissession = IRISSession.start()

        self.refresh_completions()

        history_file = self.config["main"]["history_file"]
        if history_file == "default":
            history_file = config_location() + "history"
        history = FileHistory(os.path.expanduser(history_file))

        self.prompt_app = self._build_cli(history)
        self.input = create_input()

        output = self.irissession.read(5)
        print(output)

        try:
            while True:
                try:
                    text = self.prompt_app.prompt()
                except KeyboardInterrupt:
                    continue

                command = self.execute_command(text)

                self.history.append(command)

                self.now = dt.datetime.today()

                # with self._completer_lock:
                #     self.completer.extend_history(text)

        except (iTermQuitError, EOFError):
            if not self.quiet:
                print("Goodbye!")

    def get_reserved_space(self):
        """Get the number of lines to reserve for the completion menu."""
        reserved_space_ratio = 0.45
        max_reserved_space = 8
        _, height = shutil.get_terminal_size()
        return min(int(round(height * reserved_space_ratio)), max_reserved_space)

CONTEXT_SETTINGS = {"help_option_names": ["--help"]}


@click.command(context_settings=CONTEXT_SETTINGS)
@click.option("-v", "--version", is_flag=True, help="Version of iterm.")
@click.option(
    "-n",
    "--nspace",
    "namespace_opt",
    envvar="IRIS_NAMESPACE",
    help="namespace name to connect to.",
)
@click.option(
    "-q",
    "--quiet",
    "quiet",
    is_flag=True,
    default=False,
    help="Quiet mode, skip intro on startup and goodbye on exit.",
)
@click.option(
    "-l",
    "--logfile",
    type=click.File(mode="a", encoding="utf-8"),
    help="Log every query and its results to a file.",
)
@click.option(
    "--itermrc",
    default=config_location() + "config",
    help="Location of itermrc file.",
    type=click.Path(dir_okay=False),
)
@click.option("-e", "--execute", type=str, help="Execute command and quit.")
def cli(
    version,
    namespace_opt,
    quiet,
    logfile,
    itermrc,
    execute,
):
    if version:
        print("Version:", __version__)
        sys.exit(0)

    namespace = namespace_opt.upper() if namespace_opt else None
    iterm = iTerm(
        quiet,
        logfile=logfile,
        itermrc=itermrc,
    )

    #  --execute argument
    if execute:
        try:
            # iterm.run_query(execute)
            exit(0)
        except Exception as e:
            click.secho(str(e), err=True, fg="red")
            sys.exit(1)

    if sys.stdin.isatty():
        iterm.run_cli()
    else:
        stdin = click.get_text_stream("stdin")
        stdin_text = stdin.read()

        try:
            sys.stdin = open("/dev/tty")
        except (FileNotFoundError, OSError):
            iterm.logger.warning("Unable to open TTY as stdin.")

        if (
            iterm.destructive_warning
        ):
            exit(0)
        try:
            new_line = True

            iterm.run_query(stdin_text, new_line=new_line)
            exit(0)
        except Exception as e:
            click.secho(str(e), err=True, fg="red")
            exit(1)


def has_change_db_cmd(query):
    """Determines if the statement is a database switch such as 'use' or '\\c'"""
    try:
        first_token = query.split()[0]
        if first_token.lower() in ("use", "\\c", "\\connect"):
            return True
    except Exception:
        return False

    return False


def has_change_path_cmd(sql):
    """Determines if the search_path should be refreshed by checking if the
    sql has 'set search_path'."""
    return "set search_path" in sql.lower()


def is_mutating(status):
    """Determines if the statement is mutating based on the status."""
    if not status:
        return False

    mutating = {"insert", "update", "delete"}
    return status.split(None, 1)[0].lower() in mutating


def has_meta_cmd(query):
    """Determines if the completion needs a refresh by checking if the sql
    statement is an alter, create, drop, commit or rollback."""
    try:
        first_token = query.split()[0]
        if first_token.lower() in ("alter", "create", "drop", "commit", "rollback"):
            return True
    except Exception:
        return False

    return False


def exception_formatter(e):
    return click.style(str(e), fg="red")


if __name__ == "__main__":
    cli()
