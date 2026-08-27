#!/bin/sh
# SPDX-License-Identifier: MIT
set -eu
project_dir=$(CDPATH= cd -- "$(dirname "$0")" && pwd)
exec /usr/bin/python3 "$project_dir/src/install.py" uninstall "$@"
