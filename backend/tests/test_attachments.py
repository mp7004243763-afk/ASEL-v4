import io
import sys
import unittest
import zipfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from attachments import AttachmentError, extract_attachment


class AttachmentParserTests(unittest.TestCase):
    def test_plain_text(self):
        kind, text = extract_attachment("notes.txt", b"Hello ASEL")
        self.assertEqual(kind, "document")
        self.assertEqual(text, "Hello ASEL")

    def test_csv_rows_are_extracted(self):
        kind, text = extract_attachment("table.csv", "name,value\nA,10\nB,20".encode())
        self.assertEqual(kind, "document")
        self.assertIn("A | 10", text)
        self.assertIn("B | 20", text)

    def test_unsupported_extension_is_rejected(self):
        with self.assertRaises(AttachmentError):
            extract_attachment("program.exe", b"MZ")

    def test_invalid_pdf_signature_is_rejected(self):
        with self.assertRaises(AttachmentError):
            extract_attachment("scan.pdf", b"not a pdf")

    def test_image_signature_is_checked(self):
        kind, text = extract_attachment("photo.jpg", b"\xff\xd8\xff\xd9")
        self.assertEqual(kind, "image")
        self.assertEqual(text, "")
        with self.assertRaises(AttachmentError):
            extract_attachment("fake.jpg", b"not an image")

    def test_office_archive_path_traversal_is_rejected(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w", zipfile.ZIP_DEFLATED) as archive:
            archive.writestr("../escape.txt", "unsafe")
        with self.assertRaises(AttachmentError):
            extract_attachment("bad.docx", data.getvalue())


if __name__ == "__main__":
    unittest.main()
