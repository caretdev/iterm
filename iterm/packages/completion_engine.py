from __future__ import print_function
from sqlparse.sql import Comparison, Identifier, Where
from .encodingutils import string_types, text_type
from .parseutils import last_word, extract_tables, find_prev_keyword
from .special import parse_special_command


def suggest_type(full_text, text_before_cursor):

    return [{"type": "keyword"}]

def suggest_special(text):
    text = text.lstrip()
    cmd, _, arg = parse_special_command(text)

    if cmd == text:
        # Trying to complete the special command itself
        return [{"type": "special"}]

    if cmd in ["\\.", "source", ".open", ".read"]:
        return [{"type": "file_name"}]

    return [{"type": "keyword"}, {"type": "special"}]


def _expecting_arg_idx(arg, text):
    """Return the index of expecting argument.

    >>> _expecting_arg_idx("./da", ".import ./da")
    1
    >>> _expecting_arg_idx("./data.csv", ".import ./data.csv")
    1
    >>> _expecting_arg_idx("./data.csv", ".import ./data.csv ")
    2
    >>> _expecting_arg_idx("./data.csv t", ".import ./data.csv t")
    2
    """
    args = arg.split()
    return len(args) + int(text[-1].isspace())


def identifies(id, schema, table, alias):
    return id == alias or id == table or (schema and (id == schema + "." + table))
