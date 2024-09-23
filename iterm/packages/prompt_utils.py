# -*- coding: utf-8 -*-
from __future__ import unicode_literals


import sys
import click


def confirm(*args, **kwargs):
    """Prompt for confirmation (yes/no) and handle any abort exceptions."""
    try:
        return click.confirm(*args, **kwargs)
    except click.Abort:
        return False


def prompt(*args, **kwargs):
    """Prompt the user for input and handle any abort exceptions."""
    try:
        return click.prompt(*args, **kwargs)
    except click.Abort:
        return False
