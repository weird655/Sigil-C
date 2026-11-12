#!/usr/bin/env python3
"""Sigil-C entry point. The implementation lives in the sigilc_core package."""

from sigilc_core import *  # noqa: F401,F403
from sigilc_core import cli, main  # noqa: F401
from sigilc_core.api import (  # noqa: F401
    _lsp_capabilities,
    _lsp_completion_items,
    _lsp_diagnostics,
    _lsp_document_symbols,
    _lsp_read,
    _lsp_run,
    _lsp_word_prefix,
    _lsp_write,
)

if __name__ == "__main__":
    cli()
