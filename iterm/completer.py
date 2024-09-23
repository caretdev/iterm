import logging
from re import compile, escape

from prompt_toolkit.completion import Completer, Completion

# from .packages.completion_engine import suggest_type
# from .packages.parseutils import last_word
# from .packages.special.iocommands import favoritequeries
# from .packages.filepaths import parse_path, complete_path, suggest_path

_logger = logging.getLogger(__name__)


class IRISCompleter(Completer):
    keywords = [
        "set",
        "for",
        "read",
        "open",
        "use",
        "close",
        "while",
        "merge",
    ]

    variables = [
        "$HOROLOG",
        "$JOB",
        "$NAMESPACE",
        "$TLEVEL",
        "$USERNAME",
        "$ZHOROLOG",
        "$ZJOB",
        "$ZPI",
        "$ZTIMESTAMP",
        "$ZTIMEZONE",
        "$ZVERSION",
    ]

    def __init__(self, keyword_casing="auto"):
        super(self.__class__, self).__init__()
        self.reserved_words = set()
        for x in self.keywords:
            self.reserved_words.update(x.split())
        self.name_pattern = compile(r"^[_a-z][_a-z0-9\$]*$")

        self.special_commands = []
        if keyword_casing not in ("upper", "lower", "auto"):
            keyword_casing = "auto"
        self.keyword_casing = keyword_casing
        # self.reset_completions()

    def get_completions(self, document, complete_event):
        word_before_cursor = document.get_word_before_cursor(WORD=True)
        completions = []
        suggestions = []

        return completions
