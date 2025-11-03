#!/usr/bin/env python3
import argparse
from pathlib import Path

from src.process_directory import run as run_trim
from src.transcribe_and_title import run as run_transcribe
from src.rename_from_titles import run as run_rename


def cmd_trim(ns: argparse.Namespace) -> None:
    input_dir = Path(ns.input)
    remove_silence_script = Path(__file__).parent / 'src' / 'remove_silence.py'
    target = ns.target
    run_trim(input_dir, remove_silence_script, target)


def cmd_transcribe(ns: argparse.Namespace) -> None:
    input_dir = Path(ns.input)
    run_transcribe(input_dir, None, ns.force)


def cmd_rename(ns: argparse.Namespace) -> None:
    input_dir = Path(ns.input)
    run_rename(input_dir)


def cmd_run_all(ns: argparse.Namespace) -> None:
    # Trim -> Transcribe -> Rename
    cmd_trim(ns)
    cmd_transcribe(ns)
    cmd_rename(ns)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description='SilenceRemover CLI')
    sub = p.add_subparsers(dest='cmd', required=True)

    # trim
    sp = sub.add_parser('trim', help='Trim videos in a folder')
    sp.add_argument('-i', '--input', default='/Users/mahmoud/Desktop/VIDS')
    sp.add_argument('-t', '--target', type=float, default=150.0)
    sp.set_defaults(func=cmd_trim)

    # transcribe
    sp = sub.add_parser('transcribe', help='Transcribe first 5 min and title')
    sp.add_argument('-i', '--input', default='/Users/mahmoud/Desktop/trimmed')
    sp.add_argument('--force', action='store_true')
    sp.set_defaults(func=cmd_transcribe)

    # rename
    sp = sub.add_parser('rename', help='Copy originals to renamed using titles')
    sp.add_argument('-i', '--input', default='/Users/mahmoud/Desktop/VIDS')
    sp.set_defaults(func=cmd_rename)

    # run-all
    sp = sub.add_parser('run-all', help='Trim -> Transcribe -> Rename')
    sp.add_argument('-i', '--input', default='/Users/mahmoud/Desktop/VIDS')
    sp.add_argument('-t', '--target', type=float, default=150.0)
    sp.add_argument('--force', action='store_true')
    sp.set_defaults(func=cmd_run_all)

    return p


def main() -> None:
    parser = build_parser()
    ns = parser.parse_args()
    ns.func(ns)


if __name__ == '__main__':
    main()


