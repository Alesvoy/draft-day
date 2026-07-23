#!/usr/bin/env python3
"""Compatibility entry point; use refresh_data.py for complete, safe updates."""
import sys

from refresh_data import main


if __name__ == "__main__":
    print("refresh_rankings.py is deprecated; running the complete refresh_data.py pipeline.", file=sys.stderr)
    main()
