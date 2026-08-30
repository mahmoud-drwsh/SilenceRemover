"""Deterministic OpenRouter-shaped provider used by review-analysis integration tests."""

from http.server import BaseHTTPRequestHandler, HTTPServer


TRANSCRIPT = "الحمد لله رب العالمين، اليوم نتحدث عن فضل طلب العلم."
TITLE = "اليوم نتحدث عن فضل طلب العلم"


class ProviderHandler(BaseHTTPRequestHandler):
    def do_POST(self) -> None:  # noqa: N802 - stdlib callback name
        if self.path == "/audio/transcriptions":
            body = f'{{"text":"{TRANSCRIPT}"}}'.encode()
        elif self.path == "/chat/completions":
            body = f'{{"choices":[{{"message":{{"content":"{TITLE}"}}}}]}}'.encode()
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, _format: str, *_args: object) -> None:
        pass


HTTPServer(("0.0.0.0", 8090), ProviderHandler).serve_forever()
