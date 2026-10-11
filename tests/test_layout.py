"""Reading-order layout for accessible copies (tina/layout.py)."""
import base64
import io
import shutil
import unittest
from unittest import mock

from tina.layout import _join_lines

try:
    import weasyprint
    from weasyprint.urls import URLFetcher
    HAVE_WEASYPRINT = True
except ImportError:  # pragma: no cover
    HAVE_WEASYPRINT = False


def syllabus_pdf() -> bytes:
    """An untagged, teacher-style PDF: a wrapped paragraph, a wrapped URL, and a chart mid-page."""
    from PIL import Image

    buffer = io.BytesIO()
    Image.new("RGB", (300, 160), (0, 90, 160)).save(buffer, format="PNG")
    chart = base64.b64encode(buffer.getvalue()).decode()
    html = f"""<html><body style="font-family:'DejaVu Sans';font-size:11pt;width:5in">
    <h1>ENGL 101: Composition I</h1>
    <p>This course develops academic reading and writing through drafting, peer review, and revision. Students write four essays and a final research project.</p>
    <p>The chart below shows how your final grade is weighted.</p>
    <img src="data:image/png;base64,{chart}" style="width:3in">
    <p>Course materials</p>
    <p>All readings are posted on the course site: https://canvas.coastline.edu/courses/engl101-composition-fall</p>
    </body></html>"""
    return weasyprint.HTML(string=html, url_fetcher=URLFetcher(allowed_protocols={"data"})).write_pdf()


class JoinLinesTests(unittest.TestCase):
    def test_wrapped_sentences_join_with_one_space(self):
        self.assertEqual(_join_lines(["reading and writing through", "drafting, peer review"]),
                         "reading and writing through drafting, peer review")

    def test_wrapped_urls_join_without_a_space(self):
        self.assertEqual(_join_lines(["site: https://canvas.coastline.edu/courses/", "engl101"]),
                         "site: https://canvas.coastline.edu/courses/engl101")
        self.assertEqual(_join_lines(["see www.example.edu/a-", "b today"]), "see www.example.edu/a-b today")
        self.assertEqual(_join_lines(["site: https://", "canvas.coastline.edu/x"]), "site: https://canvas.coastline.edu/x")

    def test_ordinary_hyphens_and_slashes_keep_their_space(self):
        self.assertEqual(_join_lines(["and/or", "more"]), "and/or more")


@unittest.skipUnless(HAVE_WEASYPRINT and shutil.which("pdftotext"), "needs WeasyPrint and poppler's pdftotext")
class ReadingOrderTests(unittest.TestCase):
    def test_paragraphs_stay_whole_urls_stay_intact_and_images_stay_in_place(self):
        from tina.derive import build_docmodel, docmodel_blocks

        payload = syllabus_pdf()
        model = build_docmodel(payload, title="ENGL 101", language="en-US")
        kinds = [(b["kind"], (b.get("text") or "")[:30]) for b in model["blocks"]]
        self.assertEqual([k for k, _ in kinds],
                         ["paragraph", "paragraph", "paragraph", "figure", "paragraph", "paragraph"])
        self.assertTrue(model["blocks"][1]["text"].endswith("a final research project."))
        self.assertTrue(model["blocks"][2]["text"].startswith("The chart below"))
        url = "https://canvas.coastline.edu/courses/engl101-composition-fall"
        self.assertEqual(model["blocks"][5]["links"][0]["href"], url)
        # The role index space the form uses is exactly the model's text blocks.
        self.assertEqual(len(docmodel_blocks(payload)), 5)

    def test_without_poppler_the_plain_extraction_still_works(self):
        from tina.derive import build_docmodel

        payload = syllabus_pdf()
        with mock.patch("tina.layout.shutil.which", return_value=None):
            model = build_docmodel(payload, title="ENGL 101", language="en-US")
        self.assertEqual(model["blocks"][-1]["kind"], "figure")  # fallback: images after the text
        self.assertTrue(any(b["kind"] == "paragraph" for b in model["blocks"]))


if __name__ == "__main__":
    unittest.main()
