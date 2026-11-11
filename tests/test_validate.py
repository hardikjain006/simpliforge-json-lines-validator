"""Repository-native tests for the JSON Lines validator.

Covers transformation T1, validation rule V1, the report shape in
``output/report.json``, and the material boundary cases from ``README.md``.
Run with ``python3 -m unittest discover -s tests`` from the repository root.
"""

import json
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import validate

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
VALIDATE_PY = os.path.join(REPO_ROOT, "validate.py")
FIXTURE = os.path.join(REPO_ROOT, "data", "input.jsonl")


def good_row(id_value, name="Ada Lovelace", email="ada@example.com", **extra):
    obj = {"id": id_value, "name": name, "email": email}
    obj.update(extra)
    return json.dumps(obj)


class LineSplittingTests(unittest.TestCase):
    def test_trailing_newline_is_not_an_extra_row(self):
        self.assertEqual(validate.split_lines("a\nb\n"), ["a", "b"])

    def test_missing_trailing_newline(self):
        self.assertEqual(validate.split_lines("a\nb"), ["a", "b"])

    def test_crlf_endings_stripped(self):
        self.assertEqual(validate.split_lines("a\r\nb\r\n"), ["a", "b"])

    def test_single_trailing_carriage_return_stripped(self):
        report = validate.validate_text(good_row(1) + "\r\n" + good_row(2) + "\n")
        self.assertTrue(all(row["valid"] for row in report["rows"]))


class BlankLineTests(unittest.TestCase):
    def test_empty_line(self):
        rows = validate.validate_lines([""])
        self.assertEqual(rows[0]["errors"], ["empty-line"])
        self.assertIsNone(rows[0]["id"])
        self.assertFalse(rows[0]["valid"])

    def test_whitespace_only_line_is_empty_line(self):
        for line in ("   ", "\t \t", "  \t  "):
            with self.subTest(line=line):
                rows = validate.validate_lines([line])
                self.assertEqual(rows[0]["errors"], ["empty-line"])

    def test_empty_line_never_combines_with_other_reasons(self):
        rows = validate.validate_lines(["", "   "])
        for row in rows:
            self.assertEqual(row["errors"], ["empty-line"])


class MalformedJsonTests(unittest.TestCase):
    def test_garbage_is_malformed(self):
        rows = validate.validate_lines(["{nope"])
        self.assertEqual(rows[0]["errors"], ["malformed-json"])
        self.assertIsNone(rows[0]["id"])

    def test_non_object_values_are_malformed(self):
        for line in ("[1, 2]", '"x"', "42", "null", "true", "1.5"):
            with self.subTest(line=line):
                rows = validate.validate_lines([line])
                self.assertEqual(rows[0]["errors"], ["malformed-json"])
                self.assertIsNone(rows[0]["id"])

    def test_nonstandard_constants_are_malformed(self):
        rows = validate.validate_lines(["NaN"])
        self.assertEqual(rows[0]["errors"], ["malformed-json"])

    def test_malformed_never_combines_with_other_reasons(self):
        rows = validate.validate_lines(["{bad"])
        self.assertEqual(rows[0]["errors"], ["malformed-json"])


class IdRuleTests(unittest.TestCase):
    def test_out_of_range_id(self):
        for raw in ("0", "101", "-3"):
            with self.subTest(raw=raw):
                rows = validate.validate_lines(
                    ['{"id": %s, "name": "A", "email": "a@b.c"}' % raw])
                self.assertIn("bad-id", rows[0]["errors"])

    def test_non_integer_json_numbers_are_not_integers(self):
        for raw in ("1.0", "1e2", "1.5"):
            with self.subTest(raw=raw):
                rows = validate.validate_lines(
                    ['{"id": %s, "name": "A", "email": "a@b.c"}' % raw])
                self.assertIn("bad-id", rows[0]["errors"])
                # Report id is null: not an integer per the schema definition.
                self.assertIsNone(rows[0]["id"])

    def test_non_integer_id_kinds(self):
        for obj in ('"7"', "true", "null", "[7]", '{"v": 7}'):
            with self.subTest(obj=obj):
                rows = validate.validate_lines(
                    ['{"id": %s, "name": "A", "email": "a@b.c"}' % obj])
                self.assertIn("bad-id", rows[0]["errors"])
                self.assertIsNone(rows[0]["id"])

    def test_missing_id(self):
        rows = validate.validate_lines(['{"name": "A", "email": "a@b.c"}'])
        self.assertIn("bad-id", rows[0]["errors"])
        self.assertIsNone(rows[0]["id"])

    def test_out_of_range_integer_id_reported_verbatim(self):
        rows = validate.validate_lines([good_row(101)])
        self.assertEqual(rows[0]["id"], 101)

    def test_duplicate_integer_id(self):
        rows = validate.validate_lines([good_row(5), good_row(5, name="B")])
        self.assertEqual(rows[0]["errors"], [])
        self.assertEqual(rows[1]["errors"], ["duplicate-id"])
        self.assertEqual(rows[1]["id"], 5)

    def test_first_occurrence_reserves_even_when_invalid(self):
        rows = validate.validate_lines([
            '{"id": 50, "name": "A", "email": "broken"}',
            good_row(50),
        ])
        self.assertEqual(rows[0]["errors"], ["bad-email"])
        self.assertEqual(rows[1]["errors"], ["duplicate-id"])

    def test_out_of_range_pair_duplicates(self):
        rows = validate.validate_lines([good_row(101), good_row(101)])
        self.assertEqual(rows[0]["errors"], ["bad-id"])
        self.assertEqual(rows[1]["errors"], ["bad-id", "duplicate-id"])

    def test_missing_null_and_non_integer_ids_never_duplicate(self):
        rows = validate.validate_lines([
            '{"name": "A", "email": "a@b.c"}',
            '{"name": "B", "email": "b@c.d"}',
            '{"id": null, "name": "C", "email": "c@d.e"}',
            '{"id": null, "name": "D", "email": "d@e.f"}',
            '{"id": "x", "name": "E", "email": "e@f.g"}',
            '{"id": "x", "name": "F", "email": "f@g.h"}',
            '{"id": 1.0, "name": "G", "email": "g@h.i"}',
            '{"id": 1.0, "name": "H", "email": "h@i.j"}',
        ])
        for row in rows:
            self.assertNotIn("duplicate-id", row["errors"])
            self.assertIn("bad-id", row["errors"])


class NameRuleTests(unittest.TestCase):
    def test_leading_trailing_spaces_and_tabs_stripped(self):
        rows = validate.validate_lines([good_row(1, name="  Ada\t")])
        self.assertEqual(rows[0]["errors"], [])

    def test_whitespace_only_name_invalid_after_t1(self):
        for name in ("   ", "\t", " \t "):
            with self.subTest(name=name):
                rows = validate.validate_lines([good_row(1, name=name)])
                self.assertEqual(rows[0]["errors"], ["bad-name"])

    def test_missing_and_non_string_name(self):
        rows = validate.validate_lines([
            '{"id": 1, "email": "a@b.c"}',
            '{"id": 2, "name": 42, "email": "a@b.c"}',
            '{"id": 3, "name": null, "email": "a@b.c"}',
        ])
        for row in rows:
            self.assertEqual(row["errors"], ["bad-name"])


class EmailRuleTests(unittest.TestCase):
    def test_valid_emails(self):
        for email in ("a@b.c", "ada@example.com", "x.y+z@sub.domain.org"):
            with self.subTest(email=email):
                rows = validate.validate_lines([good_row(1, email=email)])
                self.assertEqual(rows[0]["errors"], [])

    def test_invalid_emails(self):
        for email in ("not-an-email", "a@b", "a@@b.c", "@b.c", "a@b.c@",
                      "a @b.c", "a@ b.c", "a@b c.d", ""):
            with self.subTest(email=email):
                rows = validate.validate_lines([good_row(1, email=email)])
                self.assertEqual(rows[0]["errors"], ["bad-email"])

    def test_missing_and_non_string_email(self):
        rows = validate.validate_lines([
            '{"id": 1, "name": "A"}',
            '{"id": 2, "name": "A", "email": 42}',
        ])
        for row in rows:
            self.assertEqual(row["errors"], ["bad-email"])


class CanonicalOrderTests(unittest.TestCase):
    def test_error_order_bad_id_name_email(self):
        rows = validate.validate_lines(['{"name": 1}'])
        self.assertEqual(rows[0]["errors"], ["bad-id", "bad-name", "bad-email"])

    def test_error_order_with_duplicate(self):
        rows = validate.validate_lines([
            good_row(9),
            '{"id": 9, "name": "", "email": "broken"}',
        ])
        self.assertEqual(rows[1]["errors"],
                         ["duplicate-id", "bad-name", "bad-email"])

    def test_valid_means_empty_errors(self):
        rows = validate.validate_lines([good_row(1, extra="ignored")])
        self.assertEqual(rows[0]["errors"], [])
        self.assertTrue(rows[0]["valid"])
        self.assertEqual(rows[0]["id"], 1)
        self.assertEqual(rows[0]["line"], 1)


class ExtraFieldsTests(unittest.TestCase):
    def test_additional_properties_ignored(self):
        rows = validate.validate_lines(
            [good_row(1, nickname="Al", tags=[1, 2], meta={"a": 1})])
        self.assertEqual(rows[0]["errors"], [])


class ReportShapeTests(unittest.TestCase):
    def test_counts_and_file_error_null_at_100_rows(self):
        lines = [good_row(i) for i in range(1, 101)]
        report = validate.validate_text("\n".join(lines) + "\n")
        self.assertEqual(report["total_rows"], 100)
        self.assertEqual(report["valid_rows"], 100)
        self.assertEqual(report["invalid_rows"], 0)
        self.assertIsNone(report["file_error"])
        self.assertEqual(len(report["rows"]), 100)
        self.assertEqual([r["line"] for r in report["rows"]],
                         list(range(1, 101)))

    def test_short_and_long_files_still_validated_with_file_error(self):
        for count in (0, 1, 99, 101):
            with self.subTest(count=count):
                lines = [good_row(i) for i in range(1, count + 1)]
                report = validate.validate_text("\n".join(lines) + "\n"
                                                if lines else "")
                self.assertEqual(report["total_rows"], max(count, 1))
                self.assertEqual(report["file_error"], "expected-100-rows")
                self.assertEqual(report["valid_rows"] + report["invalid_rows"],
                                 report["total_rows"])

    def test_counts_add_up(self):
        report = validate.validate_text("\n".join(
            [good_row(1), "", "{bad}"]) + "\n")
        self.assertEqual(report["total_rows"], 3)
        self.assertEqual(report["valid_rows"], 1)
        self.assertEqual(report["invalid_rows"], 2)

    def test_row_entry_shape(self):
        report = validate.validate_text(good_row(3) + "\n")
        self.assertEqual(report["rows"][0],
                         {"line": 1, "id": 3, "valid": True, "errors": []})

    def test_determinism_byte_identical(self):
        text = "\n".join([good_row(i) for i in range(1, 101)]) + "\n"
        first = validate.validate_text(text)
        second = validate.validate_text(text)
        self.assertEqual(
            json.dumps(first, indent=2, ensure_ascii=False),
            json.dumps(second, indent=2, ensure_ascii=False))


class EndToEndTests(unittest.TestCase):
    def run_validator(self, input_bytes, output_path, cwd=None):
        with tempfile.NamedTemporaryFile(suffix=".jsonl",
                                         delete=False) as handle:
            handle.write(input_bytes)
            input_path = handle.name
        try:
            proc = subprocess.run(
                [sys.executable, VALIDATE_PY, input_path, output_path],
                capture_output=True, cwd=cwd or REPO_ROOT)
            return proc
        finally:
            os.unlink(input_path)

    def test_fixture_has_100_rows_covering_every_reason(self):
        with open(FIXTURE, "rb") as handle:
            raw = handle.read()
        text = raw.decode("utf-8")
        self.assertEqual(len(validate.split_lines(text)), 100)
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "report.json")
            proc = subprocess.run(
                [sys.executable, VALIDATE_PY, FIXTURE, out],
                capture_output=True, cwd=REPO_ROOT)
            self.assertEqual(proc.returncode, 0, proc.stderr.decode())
            with open(out, encoding="utf-8") as handle:
                report = json.load(handle)
        self.assertEqual(report["total_rows"], 100)
        self.assertIsNone(report["file_error"])
        self.assertEqual(report["valid_rows"] + report["invalid_rows"], 100)
        seen = set()
        for row in report["rows"]:
            seen.update(row["errors"])
            self.assertEqual(row["valid"], row["errors"] == [])
        for reason in ("empty-line", "malformed-json", "bad-id",
                       "duplicate-id", "bad-name", "bad-email"):
            self.assertIn(reason, seen)

    def test_crlf_input_end_to_end(self):
        body = ("\r\n".join([good_row(1), good_row(2)]) + "\r\n").encode()
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "report.json")
            proc = self.run_validator(body, out)
            self.assertEqual(proc.returncode, 0, proc.stderr.decode())
            with open(out, encoding="utf-8") as handle:
                report = json.load(handle)
        self.assertEqual(report["total_rows"], 2)
        self.assertTrue(all(row["valid"] for row in report["rows"]))

    def test_short_file_reports_expected_100_rows(self):
        body = (good_row(1) + "\n").encode()
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "report.json")
            proc = self.run_validator(body, out)
            self.assertEqual(proc.returncode, 0, proc.stderr.decode())
            with open(out, encoding="utf-8") as handle:
                report = json.load(handle)
        self.assertEqual(report["total_rows"], 1)
        self.assertEqual(report["file_error"], "expected-100-rows")

    def test_non_utf8_input_fails_without_touching_report(self):
        body = b'{"id": 1, "name": "A", "email": "a@b.c"}\n\xff\xfe\n'
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "report.json")
            with open(out, "wb") as handle:
                handle.write(b'{"sentinel": true}')
            proc = self.run_validator(body, out)
            self.assertNotEqual(proc.returncode, 0)
            with open(out, "rb") as handle:
                self.assertEqual(handle.read(), b'{"sentinel": true}')

    def test_non_utf8_input_creates_no_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "report.json")
            proc = self.run_validator(b"\xff\xfe\n", out)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(os.path.exists(out))

    def test_missing_input_fails_without_report(self):
        with tempfile.TemporaryDirectory() as tmp:
            out = os.path.join(tmp, "report.json")
            proc = subprocess.run(
                [sys.executable, VALIDATE_PY,
                 os.path.join(tmp, "does-not-exist.jsonl"), out],
                capture_output=True, cwd=REPO_ROOT)
            self.assertNotEqual(proc.returncode, 0)
            self.assertFalse(os.path.exists(out))


if __name__ == "__main__":
    unittest.main()
