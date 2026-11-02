#!/bin/bash
set -Eeuo pipefail
# Start the interfaces and background downloads under one supervisor.
exec "${COMFYUI_PYTHON:-/opt/venv/bin/python}" "${TEMPLATE_HOME:-/opt/template}/launch.py" "$@"
