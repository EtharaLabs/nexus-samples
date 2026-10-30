#!/bin/bash
# GENERATED SECTION. DO NOT HAND-EDIT.
set -euo pipefail
# Oracle: install the reference engine as /app/stream.
install -D -m 0755 /solution/reference.py /app/stream
sed -i "1s|.*|#!/usr/bin/env python3|" /app/stream
