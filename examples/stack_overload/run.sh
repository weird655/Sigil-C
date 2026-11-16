#!/usr/bin/env bash
set -eu
cd "$(dirname "$0")"
python3 ../../sigilc.py real.sigil -o real.c --no-bounds-check
cc -std=c99 -O0 -g -fsanitize=address -fno-omit-frame-pointer real.c -o real
./real || true
