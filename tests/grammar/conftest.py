import pytest

from lark import Lark
from lark.indenter import (
    Indenter,
)


class PythonIndenter(Indenter):
    NL_type = '_NEWLINE'
    OPEN_PAREN_types = ['LPAR', 'LSQB', 'LBRACE']
    CLOSE_PAREN_types = ['RPAR', 'RSQB', 'RBRACE']
    INDENT_type = '_INDENT'
    DEDENT_type = '_DEDENT'
    tab_len = 4


def get_lark_grammar():
    return Lark.open(
        'tests/grammar/vyper.lark',
        parser='lalr',
        start='file_input',
        postlex=PythonIndenter()
    )


@pytest.fixture
def lark_grammar():
    return get_lark_grammar()