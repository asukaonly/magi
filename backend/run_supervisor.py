#!/usr/bin/env python3
"""Magi dual-process backend supervisor launcher."""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

from magi.backend_supervisor import main


if __name__ == "__main__":
    main()
