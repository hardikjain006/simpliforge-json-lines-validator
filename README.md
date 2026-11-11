# JSON Lines Validator

## Goal

Validate a 100-row JSON Lines fixture: apply one normalization
transformation, enforce one row-validity rule, and emit one
machine-readable validation report.

Determinism requirement: identical input bytes always produce a
byte-identical report. The report contains no timestamps, randomness,
or environment-dependent values.

## Public inputs

- `data/input.jsonl`: UTF-8 text of exactly 100 lines, one JSON object
  per line (JSON Lines). Lines are split on `\n`; a trailing `\r`
  (CRLF endings) is stripped before parsing, and a single trailing
  newline at end of file does not count as an extra row.
- Row schema (all fields required; additional properties, when present,
  are ignored and do not affect validity):
  - `id`: integer, 1-100 inclusive, unique across the file (see V1 rule
    2 for duplicate scope). `id` is an integer if and only if it is a
    JSON number whose text matches `-?(0|[1-9][0-9]*)` (no fraction
    part, no exponent). In particular `1.0`, `1e2`, `1.5`, strings,
    booleans, `null`, arrays, and objects are not integers.
  - `name`: string (judged after transformation T1 below).
  - `email`: string.
- Example rows:
  - `{"id": 1, "name": " Ada Lovelace ", "email": "ada@example.com"}`
  - `{"id": 2, "name": "Alan Turing", "email": "alan@example.org"}`

## Transformation (one): T1 normalize `name`

Strip leading and trailing whitespace (spaces and tabs) from the
`name` field. No other field is altered. The transformation applies
before validation, so `name` is judged on its normalized value.

## Validation rule (one): V1 row validity

A row is valid if and only if all of the following hold:

1. The line parses as a JSON object. Malformed JSON, or valid JSON
   that is not an object (array, string, number, `true`/`false`,
   `null`), is invalid with exactly `["malformed-json"]` and no other
   reason.
2. `id` is an integer in [1, 100] (reason `bad-id`; a missing `id`
   is also `bad-id`). Duplicate tracking applies only to
   integer-valued `id`s as defined above, regardless of range
   validity: the first file-order occurrence of an integer value
   reserves it even when that row is otherwise invalid, and each later
   row with the same integer value is invalid (reason `duplicate-id`,
   plus any other applicable reasons). Rows with a missing, `null`,
   or non-integer `id` never reserve a value and never receive
   `duplicate-id`.
3. The normalized `name` is non-empty (reason `bad-name`; a missing
   or non-string `name` is also `bad-name`).
4. `email` matches `^[^@\s]+@[^@\s]+\.[^@\s]+$`: exactly one `@`,
   a non-empty local part, and a domain containing at least one `.`
   (reason `bad-email`; a missing or non-string `email` is also
   `bad-email`).

A blank or whitespace-only line is a row and is invalid with exactly
`["empty-line"]` and no other reason.

## Output (one): validation report

- `output/report.json`: UTF-8 JSON object with:
  - `total_rows`: number of input lines processed.
  - `valid_rows`, `invalid_rows`: row counts (`valid_rows +
    invalid_rows == total_rows`).
  - `file_error`: `null` when the input has exactly 100 rows,
    otherwise `"expected-100-rows"`. A short or long file is still
    validated line by line; the count mismatch is reported here,
    not by refusing to validate.
  - `rows`: one entry per input line, in input-line order:
    `{"line": N, "id": <id or null>, "valid": bool, "errors": [...]}`,
    where `line` is the 1-based line number, `id` is the row's `id`
    when the line parsed as an object with an integer `id` per the
    schema definition above (else `null`), and `errors` lists the
    applicable reasons in this canonical order: `empty-line`,
    `malformed-json`, `bad-id`, `duplicate-id`, `bad-name`,
    `bad-email`. `empty-line` and `malformed-json` never appear with
    any other reason. A row is valid if and only if `errors` is empty
    (`valid == (errors is empty)`).
- Non-UTF-8 input is a file-level failure: the validator must not
  create or update `output/report.json` into a report satisfying the
  success schema above (`total_rows` / `valid_rows` / `invalid_rows` /
  `file_error` / `rows`), and the run must be exposed as failed by the
  implementation-phase harness (which owns the invocation surface). A
  test passes if and only if no new success-shaped `report.json` is
  produced for a non-UTF-8 input.

## Material boundary cases

| Case | Required behavior |
| ---- | ----------------- |
| Exactly 100 valid rows | `file_error` is `null`, all rows valid |
| Blank / whitespace-only line | Invalid row, exactly `["empty-line"]` |
| Malformed JSON line | Invalid row, exactly `["malformed-json"]`, `id` is `null` |
| Non-object JSON value (`[]`, `"x"`, `42`, `null`) | Invalid row, exactly `["malformed-json"]`, `id` is `null` |
| `id` written as `1.0`, `1e2`, or `1.5` | Not an integer: invalid row, reason `bad-id`, report `id` is `null` |
| Duplicate integer `id` | First occurrence judged normally and reserves the value; repeats invalid with `duplicate-id` (plus any other applicable reasons, in canonical order) |
| Two rows with out-of-range integer `id` (e.g. `101`) | First row `["bad-id"]`; second row `["bad-id", "duplicate-id"]` |
| Two rows with missing / `null` / non-integer `id` | Neither row receives `duplicate-id` |
| Missing field | Fails the corresponding `bad-*` reason |
| Extra object fields | Ignored; do not affect validity |
| Name that is only whitespace | Invalid after T1, reason `bad-name` |
| File with != 100 lines | Validate every line anyway; `file_error` is `"expected-100-rows"` |
| CRLF line endings | Trailing `\r` stripped before parsing |
| Non-UTF-8 input bytes | No new success-shaped `report.json`; run exposed as failed |

## Non-goals

No additional transformations, validation rules, outputs, command-line
surface, or language/runtime choice is prescribed here. The
implementation phase selects tooling and additionally provides the
`data/input.jsonl` fixture (100 rows, covering at least one instance
of each error reason) and the validator that produces
`output/report.json`.

## Unresolved requirements

None. This contract is implementable as written.

## Running the validator (implementation)

- Requires Python 3.8+ with no third-party dependencies.
- `python3 validate.py` reads `data/input.jsonl` and writes
  `output/report.json` (created when missing).
- `python3 validate.py <input> <output>` overrides either path.
- Exit code `0` when a report was written. Row-level failures and a
  row-count mismatch are data inside the report (including
  `file_error`), not process failures. File-level failures (missing or
  unreadable input, non-UTF-8 input bytes) exit non-zero and never
  create or update the report file.
- `python3 -m unittest discover -s tests` runs the test suite.
