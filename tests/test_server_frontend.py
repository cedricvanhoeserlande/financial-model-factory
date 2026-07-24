from __future__ import annotations

import importlib
import json
import re
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]


class ServerFrontendTest(unittest.TestCase):
    def test_health_endpoint_reports_current_local_server(self) -> None:
        from backend.app import server as server_module

        server_module = importlib.reload(server_module)
        httpd = server_module.create_server("127.0.0.1", 0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{httpd.server_address[1]}/api/health"
            with urllib.request.urlopen(url, timeout=5) as response:
                payload = json.loads(response.read().decode("utf-8"))
            self.assertTrue(payload["ok"])
            self.assertEqual(payload["server"], "ModelFactoryLocal")
            self.assertNotIn("version", payload)
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)

    def test_missing_frontend_build_fails_with_clear_message(self) -> None:
        from backend.app import server as server_module

        server_module = importlib.reload(server_module)
        previous_dist = server_module.FRONTEND_DIST_DIR
        server_module.FRONTEND_DIST_DIR = ROOT / "tests" / ".tmp_missing_frontend_dist"
        httpd = server_module.create_server("127.0.0.1", 0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            url = f"http://127.0.0.1:{httpd.server_address[1]}/"
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(url, timeout=5)
            error = raised.exception
            self.assertEqual(error.code, 503)
            payload = json.loads(error.read().decode("utf-8"))
            error.close()
            self.assertIn("Frontend build missing", payload["error"])
            self.assertIn("npm run build", payload["error"])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)
            server_module.FRONTEND_DIST_DIR = previous_dist

    def test_missing_model_get_routes_return_structured_json_errors(self) -> None:
        from backend.app import server as server_module

        server_module = importlib.reload(server_module)
        httpd = server_module.create_server("127.0.0.1", 0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{httpd.server_address[1]}"
            for path in [
                "/api/workspace?model_id=does-not-exist",
                "/api/builds?model_id=does-not-exist",
                "/api/runs/latest?model_id=does-not-exist",
            ]:
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(f"{base}{path}", timeout=5)
                error = raised.exception
                self.assertEqual(error.code, 404)
                payload = json.loads(error.read().decode("utf-8"))
                error.close()
                self.assertEqual(payload["code"], "model_not_found")
                self.assertEqual(payload["model_id"], "does-not-exist")
                self.assertEqual(payload["error"], "Model not found")
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)

    def test_invalid_model_id_get_route_returns_structured_bad_request(self) -> None:
        from backend.app import server as server_module

        server_module = importlib.reload(server_module)
        httpd = server_module.create_server("127.0.0.1", 0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{httpd.server_address[1]}"
            with self.assertRaises(urllib.error.HTTPError) as raised:
                urllib.request.urlopen(f"{base}/api/workspace?model_id=..%2Fsecret", timeout=5)
            error = raised.exception
            self.assertEqual(error.code, 400)
            payload = json.loads(error.read().decode("utf-8"))
            error.close()
            self.assertEqual(payload["code"], "bad_request")
            self.assertIn("Invalid model id", payload["error"])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)

    def test_regular_rerun_input_schema_error_returns_structured_bad_request(self) -> None:
        from backend.app import server as server_module

        server_module = importlib.reload(server_module)
        httpd = server_module.create_server("127.0.0.1", 0)
        thread = threading.Thread(target=httpd.serve_forever, daemon=True)
        thread.start()
        try:
            base = f"http://127.0.0.1:{httpd.server_address[1]}"
            request = urllib.request.Request(
                f"{base}/api/run",
                data=json.dumps({"model_id": "model-1", "input_params": {}}).encode("utf-8"),
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with mock.patch.object(
                server_module.model_loop,
                "execute_run",
                side_effect=RuntimeError("Submitted inputs do not match this model's input schema. Missing required inputs: drivers.revenue."),
            ):
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(request, timeout=5)
            error = raised.exception
            self.assertEqual(error.code, 400)
            payload = json.loads(error.read().decode("utf-8"))
            error.close()
            self.assertEqual(payload["code"], "invalid_run_inputs")
            self.assertIn("Missing required inputs", payload["error"])
        finally:
            httpd.shutdown()
            httpd.server_close()
            thread.join(timeout=5)

    def test_frontend_model_index_uses_explicit_test_metadata(self) -> None:
        source = (ROOT / "frontend" / "src" / "App.tsx").read_text(encoding="utf-8")
        match = re.search(r"function isDeveloperModel\(model: ModelManifest\): boolean \{(?P<body>.*?)\n\}", source, re.S)
        self.assertIsNotNone(match)
        body = match.group("body")
        self.assertIn("artifact_kind", body)
        self.assertNotIn('.includes("test")', body)
        self.assertNotIn('.includes("browser")', body)

    def test_frontend_file_server_rejects_resolved_sibling_path(self) -> None:
        from backend.app import server as server_module

        with tempfile.TemporaryDirectory() as temporary_dir:
            parent = Path(temporary_dir)
            dist = parent / "dist"
            sibling = parent / "dist-private"
            dist.mkdir()
            sibling.mkdir()
            (dist / "index.html").write_text("index", encoding="utf-8")
            (sibling / "secret.txt").write_text("secret", encoding="utf-8")

            previous_dist = server_module.FRONTEND_DIST_DIR
            server_module.FRONTEND_DIST_DIR = dist
            httpd = server_module.create_server("127.0.0.1", 0)
            thread = threading.Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                url = f"http://127.0.0.1:{httpd.server_address[1]}/../dist-private/secret.txt"
                with self.assertRaises(urllib.error.HTTPError) as raised:
                    urllib.request.urlopen(url, timeout=5)
                error = raised.exception
                self.assertEqual(error.code, 404)
                error.close()
            finally:
                httpd.shutdown()
                httpd.server_close()
                thread.join(timeout=5)
                server_module.FRONTEND_DIST_DIR = previous_dist


if __name__ == "__main__":
    unittest.main()
