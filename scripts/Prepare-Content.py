#!/usr/bin/env python3
"""Materialize the locally pinned OMH payload with ATM's shared Rust validator."""
import argparse
import subprocess
import sys
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', type=Path)
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    cli = args.cli
    if cli is None:
        subprocess.run(['cargo', 'build', '--locked', '-p', 'atm-cli'], cwd=root, check=True)
        cli = root / 'target/debug' / ('atm.exe' if sys.platform == 'win32' else 'atm')
    subprocess.run([str(cli.resolve(strict=True)), 'harness', 'fetch', '--lock', str(root / 'content/omh.lock.json'),
                    '--output', str(root / 'harness')], cwd=root, check=True)


if __name__ == '__main__':
    main()
