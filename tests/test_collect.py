"""Offline tests: local fake source site + fake AI. Run: python -m unittest discover -s tests"""
import datetime as dt
import functools
import http.server
import io
import json
import sys
import tempfile
import threading
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import collect  # noqa: E402


def make_pdf(lines=None, blank_pages=0) -> bytes:
    from reportlab.pdfgen import canvas
    buf = io.BytesIO()
    c = canvas.Canvas(buf)
    for line_set in (lines or []):
        y = 800
        for line in line_set:
            c.drawString(50, y, line)
            y -= 18
        c.showPage()
    for _ in range(blank_pages):
        c.rect(50, 50, 200, 200, fill=1)  # image-like page with no text
        c.showPage()
    c.save()
    return buf.getvalue()


NOTICE_LINES = [[
    "Government of Telangana - Agriculture Department",
    "G.O.Rt.No. 123 Dated 10-10-2026",
    "Rythu Bharosa: Rs.6,000 per acre per season to eligible farmers.",
    "Applications at Rythu Vedika before 30-11-2026. Pattadar passbook required.",
]]
LISTING = """<html><body>
<a href="/docs/go123.pdf">G.O. 123 Rythu Bharosa farmers assistance</a>
<a href="/docs/scanned.pdf">Rythu circular (scanned copy)</a>
<a href="/docs/broken.pdf">Farmer crop loan circular</a>
<a href="/docs/sports.pdf">Sports meet schedule</a>
<a href="https://evil.example.com/farmer.pdf">Farmer scheme (fake site)</a>
<a href="javascript:alert(1)">Farmer click</a>
<a href="/redirect-out">Farmer redirect</a>
</body></html>"""


class Handler(http.server.BaseHTTPRequestHandler):
    files = {}

    def log_message(self, *a):
        pass

    def do_GET(self):
        if self.path == "/redirect-out":
            self.send_response(302)
            self.send_header("Location", "https://evil.example.com/steal")
            self.end_headers()
            return
        body, ctype = self.files.get(self.path, (None, None))
        if body is None:
            self.send_response(404)
            self.end_headers()
            return
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def fake_ai(document_text, link_text, url, api_key):
    if "Sports" in link_text:
        return json.dumps({"relevant": False})
    if "Ignore previous" in document_text:
        return "I will ignore the rules"  # simulated prompt-injection success -> must be rejected
    return "```json\n" + json.dumps({
        "relevant": True,
        "titleTe": "రైతు భరోసా సహాయం",
        "title": "Rythu Bharosa assistance",
        "date": "2026-10-10",
        "deadline": "2026-11-30",
        "department": "Agriculture Department",
        "category": "Payments",
        "state": "Approved Government Order",
        "pointsTe": ["అర్హులైన రైతులకు ఎకరాకు సీజన్‌కు ₹6,000", "30-11-2026 లోపు రైతు వేదికలో దరఖాస్తు"],
        "pointsEn": ["Rs.6,000 per acre per season for eligible farmers", "Apply at Rythu Vedika before 30-11-2026"],
        "extra_field": "<script>alert(1)</script>",
    }) + "\n```"


class CollectorTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        Handler.files = {
            "/list": (LISTING.encode(), "text/html; charset=utf-8"),
            "/docs/go123.pdf": (make_pdf(NOTICE_LINES), "application/pdf"),
            "/docs/scanned.pdf": (make_pdf(blank_pages=3), "application/pdf"),
            "/docs/broken.pdf": (b"%PDF-1.4\n garbage " * 50, "application/pdf"),
            "/docs/sports.pdf": (make_pdf([["Annual sports meet schedule"]]), "application/pdf"),
        }
        cls.srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.port = cls.srv.server_address[1]
        threading.Thread(target=cls.srv.serve_forever, daemon=True).start()
        cls.base = f"http://127.0.0.1:{cls.port}"
        cls.hosts = {"127.0.0.1"}

    @classmethod
    def tearDownClass(cls):
        cls.srv.shutdown()

    # ---- allow-list -------------------------------------------------------
    def test_allow_list(self):
        self.assertTrue(collect.host_allowed("https://agri.telangana.gov.in/x.pdf", set()))
        self.assertTrue(collect.host_allowed("https://pmkisan.gov.in/", set()))
        self.assertFalse(collect.host_allowed("https://gov.in.evil.com/", set()))
        self.assertFalse(collect.host_allowed("https://evilgov.in/", set()))
        self.assertFalse(collect.host_allowed("file:///etc/passwd", set()))
        self.assertFalse(collect.host_allowed("ftp://agri.telangana.gov.in/", set()))
        self.assertFalse(collect.host_allowed("http://169.254.169.254/latest", set()))

    def test_redirect_off_allow_list_blocked(self):
        with self.assertRaises(Exception):
            collect.fetch(self.base + "/redirect-out", 10_000, self.hosts)

    # ---- link discovery ---------------------------------------------------
    def test_candidates(self):
        found = collect.find_candidates({}, LISTING.encode(), "text/html", self.base + "/list", self.hosts)
        urls = [u for u, _ in found]
        self.assertIn(self.base + "/docs/go123.pdf", urls)
        self.assertNotIn(self.base + "/docs/sports.pdf", urls)          # not farmer related
        self.assertFalse(any("evil.example.com" in u for u in urls))     # off allow-list
        self.assertFalse(any(u.startswith("javascript") for u in urls))

    # ---- reading notices --------------------------------------------------
    def test_read_text_pdf_full(self):
        text, status, _ = collect.read_notice(self.base + "/docs/go123.pdf", self.hosts)
        self.assertIn("6,000", text)
        self.assertEqual(status, "full")

    def test_read_scanned_pdf(self):
        text, status, _ = collect.read_notice(self.base + "/docs/scanned.pdf", self.hosts)
        self.assertEqual(status, "scanned")

    def test_broken_pdf_handled(self):
        text, status, _ = collect.read_notice(self.base + "/docs/broken.pdf", self.hosts)
        self.assertEqual(text, "")
        self.assertEqual(status, "scanned")

    def test_size_cap(self):
        with self.assertRaises(ValueError):
            collect.fetch(self.base + "/docs/go123.pdf", 100, self.hosts)

    # ---- AI output validation --------------------------------------------
    def test_summary_validation(self):
        ok = collect.parse_summary(fake_ai("x", "G.O.", "u", "k"))
        self.assertEqual(ok["category"], "Payments")
        self.assertNotIn("extra_field", ok)                               # unknown fields dropped
        self.assertIsNone(collect.parse_summary("not json"))
        self.assertIsNone(collect.parse_summary(json.dumps({"relevant": True, "title": "x",
                                                             "pointsTe": ["English only"], "pointsEn": ["x"]})))
        bad = json.loads(fake_ai("x", "G.O.", "u", "k").strip("`json\n"))
        bad.update(category="Hacked", state="Paid!!", date="2026-13-45")
        res = collect.parse_summary(json.dumps(bad))
        self.assertEqual((res["category"], res["state"], res["date"]), ("Other", "Advisory / information", ""))

    # ---- end to end -------------------------------------------------------
    def test_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "sources.json").write_text(json.dumps([
                {"name": "Test source", "url": self.base + "/list", "extraHosts": ["127.0.0.1"]}]))
            patches = [
                mock.patch.object(collect, "DATA", tmp), mock.patch.object(collect, "ALERTS_FILE", tmp / "alerts.json"),
                mock.patch.object(collect, "ARCHIVE_FILE", tmp / "archive.json"),
                mock.patch.object(collect, "SEEN_FILE", tmp / "seen.json"),
                mock.patch.object(collect, "SOURCES_FILE", tmp / "sources.json"),
                mock.patch.object(collect, "call_ai", side_effect=fake_ai),
                mock.patch.dict("os.environ", {"MODELS_TOKEN": "test-token", "AI_PROVIDER": "github"}),
            ]
            for p in patches:
                p.start()
            try:
                self.assertEqual(collect.run(), 0)
                feed = json.loads((tmp / "alerts.json").read_text())
                self.assertIsNotNone(feed["lastChecked"])
                self.assertEqual(len(feed["alerts"]), 1)
                a = feed["alerts"][0]
                self.assertEqual((a["review"], a["fullText"], a["deadline"]), ("auto", "full", "2026-11-30"))
                seen = json.loads((tmp / "seen.json").read_text())
                self.assertEqual(seen[self.base + "/docs/scanned.pdf"]["result"], "needs-review")
                self.assertEqual(seen[self.base + "/docs/broken.pdf"]["result"], "needs-review")
                self.assertFalse(any("scanned" in x["url"] for x in feed["alerts"]))  # never guessed
                # second run: nothing duplicated
                self.assertEqual(collect.run(), 0)
                self.assertEqual(len(json.loads((tmp / "alerts.json").read_text())["alerts"]), 1)
            finally:
                for p in patches:
                    p.stop()

    def test_missing_key_fails_securely(self):
        with mock.patch.dict("os.environ", {"MODELS_TOKEN": "", "ANTHROPIC_API_KEY": "", "AI_PROVIDER": "github"}):
            self.assertEqual(collect.run(), 1)
        with mock.patch.dict("os.environ", {"MODELS_TOKEN": "x", "ANTHROPIC_API_KEY": "", "AI_PROVIDER": "anthropic"}):
            self.assertEqual(collect.run(), 1)   # provider switch needs its own key

    def test_github_models_request(self):
        captured = {}

        class AIHandler(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def do_POST(self):
                captured["auth"] = self.headers.get("Authorization")
                captured["body"] = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                reply = {"choices": [{"message": {"role": "assistant", "content": fake_ai("doc", "G.O.", "u", "k")}}]}
                out = json.dumps(reply).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(out)))
                self.end_headers()
                self.wfile.write(out)

        srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), AIHandler)
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            with mock.patch.object(collect, "GITHUB_MODELS_URL", f"http://127.0.0.1:{srv.server_address[1]}/x"), \
                 mock.patch.dict("os.environ", {"AI_PROVIDER": "github", "AI_MODEL": ""}):
                raw = collect.call_ai("notice text", "G.O.", "https://agri.telangana.gov.in/a.pdf", "tok123")
        finally:
            srv.shutdown()
            srv.server_close()
        self.assertEqual(captured["auth"], "Bearer tok123")
        self.assertEqual(captured["body"]["messages"][0]["role"], "system")
        self.assertIn("<document>", captured["body"]["messages"][1]["content"])
        self.assertTrue(collect.parse_summary(raw)["relevant"])

    def test_text_cap_by_provider(self):
        with mock.patch.dict("os.environ", {"AI_PROVIDER": "github"}):
            self.assertEqual(collect.text_cap(), 16_000)
        with mock.patch.dict("os.environ", {"AI_PROVIDER": "anthropic"}):
            self.assertEqual(collect.text_cap(), 60_000)

    # ---- retention --------------------------------------------------------
    def test_expiry_and_archive(self):
        today = dt.date(2026, 10, 15)
        alerts = [
            {"url": "a", "deadline": "2026-10-01", "state": "Applications open", "addedAt": "2026-09-20T10:00:00+05:30"},
            {"url": "b", "deadline": "", "state": "Advisory / information", "addedAt": "2026-06-01T10:00:00+05:30"},
            {"url": "c", "deadline": "2026-12-31", "state": "Applications open", "addedAt": "2026-06-01T10:00:00+05:30"},
        ]
        keep, archive = collect.maintain(alerts, [], today)
        self.assertEqual({a["url"] for a in keep}, {"a", "c"})          # c kept: deadline still open
        self.assertEqual(archive[0]["url"], "b")                          # moved, not deleted
        self.assertEqual(next(a for a in keep if a["url"] == "a")["state"], "Expired / closed")


if __name__ == "__main__":
    unittest.main()
