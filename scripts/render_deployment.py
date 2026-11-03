#!/usr/bin/env python3
"""Render deployment bundles without installing application dependencies."""
import sys

from deployment import main


if __name__ == "__main__":
    raise SystemExit(main(["render", *sys.argv[1:]]))
