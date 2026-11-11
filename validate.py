#!/usr/bin/env python3
"""JSON Lines validator.

Reads a JSON Lines input file (default ``data/input.jsonl``), applies
transformation T1 (normalize ``name``), enforces validation rule V1 (row
validity), and writes the machine-readable validation report
(default ``output/report.json``).

The public requirements contract is defined in ``README.md``. This module
implements exactly that contract using only the Python standard library.

Exit status: ``0`` when a report was written. Row-level failures and a
row-count mismatch are data inside the report, not process failures.
File-level failures (missing or unreadable input, non-UTF-8 input bytes)
return non-zero and never create or update the report file.
"""

import json
import os
import re
import sys

# Python 3.11 caps int<->str conversion digits; a very long digit string is
# still valid JSON and must be judged as bad-id, not as malformed-json.
try:
    sys.set_int_max_str_digits(1000000)
except AttributeError:  # pragma: no cover - Python < 3.11 has no cap
    pass

EXPECTED_ROWS = 100
FILE_ERROR_MESSAGE = "expected-100-rows"

# V1 rule 4: exactly one '@', a non-empty local part, and a domain
# containing at least one '.'. Neither side may contain '@' or whitespace.
EMAIL_RE = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")

# Canonical reason order for the report's `errors` lists.
ERROR_EMPTY_LINE = "empty-line"
ERROR_MALFORMED_JSON = "malformed-json"
ERROR_BAD_ID = "bad-id"
ERROR_DUPLICATE_ID = "duplicate-id"
ERROR_BAD_NAME = "bad-name"
ERROR_BAD_EMAIL = "bad-email"


def _reject_constant(text):
    """Reject non-standard JSON constants (NaN, Infinity, -Infinity)."""
    raise ValueError("non-standard JSON constant: %r" % (text,))


def _is_integer_id(value):
    """True when value is an integer-valued id per the row schema.

    The id is an integer if and only if it is a JSON number whose text
    matches ``-?(0|[1-9][0-9]*)``. Python's ``json`` decoder produces
    ``int`` exactly for such literals (fraction/exponent forms decode to
    ``float``; leading-zero and ``+`` forms are rejected outright), so an
    ``int`` check -- excluding ``bool``, which subclasses ``int`` --
    implements the schema definition.
    """
    return isinstance(value, int) and not isinstance(value, bool)


def split_lines(text):
    """Split input text into rows per the public inputs contract.

    Lines are split on ``\\n``; one trailing ``\\r`` per line (CRLF) is
    stripped; a single trailing newline at end of file is not an extra row.
    """
    if text.endswith("\n"):
        text = text[:-1]
    lines = text.split("\n")
    return [line[:-1] if line.endswith("\r") else line for line in lines]


def validate_lines(lines):
    """Validate already-split input lines; return the ``rows`` report list."""
    rows = []
    seen_ids = set()
    for line_number, line in enumerate(lines, start=1):
        if line.strip() == "":
            rows.append({
                "line": line_number,
                "id": None,
                "valid": False,
                "errors": [ERROR_EMPTY_LINE],
            })
            continue
        try:
            value = json.loads(line, parse_constant=_reject_constant)
        except (ValueError, RecursionError):
            value = None
        if not isinstance(value, dict):
            rows.append({
                "line": line_number,
                "id": None,
                "valid": False,
                "errors": [ERROR_MALFORMED_JSON],
            })
            continue

        errors = []
        raw_id = value.get("id")
        integer_id = _is_integer_id(raw_id)
        report_id = raw_id if integer_id else None
        if not integer_id or not 1 <= raw_id <= 100:
            errors.append(ERROR_BAD_ID)
        if integer_id:
            if raw_id in seen_ids:
                errors.append(ERROR_DUPLICATE_ID)
            else:
                # The first file-order occurrence reserves the value even
                # when this row is otherwise invalid.
                seen_ids.add(raw_id)

        name = value.get("name")
        if not isinstance(name, str) or name.strip(" \t") == "":
            errors.append(ERROR_BAD_NAME)

        email = value.get("email")
        if not isinstance(email, str) or EMAIL_RE.fullmatch(email) is None:
            errors.append(ERROR_BAD_EMAIL)

        rows.append({
            "line": line_number,
            "id": report_id,
            "valid": not errors,
            "errors": errors,
        })
    return rows


def build_report(lines):
    """Build the full validation report object for already-split lines."""
    rows = validate_lines(lines)
    valid_rows = sum(1 for row in rows if row["valid"])
    return {
        "total_rows": len(rows),
        "valid_rows": valid_rows,
        "invalid_rows": len(rows) - valid_rows,
        "file_error": None if len(rows) == EXPECTED_ROWS else FILE_ERROR_MESSAGE,
        "rows": rows,
    }


def validate_text(text):
    """Validate raw input text; return the full report object."""
    return build_report(split_lines(text))


def main(argv):
    repo_root = os.path.dirname(os.path.abspath(__file__))
    input_path = argv[1] if len(argv) > 1 else os.path.join(repo_root, "data", "input.jsonl")
    output_path = argv[2] if len(argv) > 2 else os.path.join(repo_root, "output", "report.json")

    try:
        with open(input_path, "rb") as handle:
            raw = handle.read()
    except OSError as exc:
        print("error: cannot read input %r: %s" % (input_path, exc), file=sys.stderr)
        return 1

    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        print("error: input %r is not valid UTF-8: %s" % (input_path, exc), file=sys.stderr)
        return 1

    report = validate_text(text)

    output_dir = os.path.dirname(output_path)
    if output_dir:
        try:
            os.makedirs(output_dir, exist_ok=True)
        except OSError as exc:
            print("error: cannot create output directory %r: %s" % (output_dir, exc),
                  file=sys.stderr)
            return 1
    try:
        with open(output_path, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(report, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    except OSError as exc:
        print("error: cannot write report %r: %s" % (output_path, exc), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
