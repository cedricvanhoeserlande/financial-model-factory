from __future__ import annotations

import argparse
import json
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlparse

from backend.app import model_loop, paint_showcase

ROOT_DIR = Path(__file__).resolve().parents[2]
FRONTEND_DIR = ROOT_DIR / "frontend"
FRONTEND_DIST_DIR = FRONTEND_DIR / "dist"


class ModelFactoryHandler(BaseHTTPRequestHandler):
    server_version = "ModelFactoryLocal"

    def log_message(self, format: str, *args: Any) -> None:
        return

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        try:
            if self._dispatch_get(parsed):
                return
            if parsed.path.startswith("/api/"):
                self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
                return
            self._serve_frontend(parsed.path)
        except Exception as exc:
            self._send_api_error(exc)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        try:
            payload = self._read_json_body()
            if self._dispatch_post(parsed.path, payload):
                return
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
        except Exception as exc:
            self._send_api_error(exc)

    def _dispatch_get(self, parsed) -> bool:
        routes = {
            "/api/health": self._get_health,
            "/api/workspace": self._get_workspace,
            "/api/models": self._get_models,
            "/api/builds": self._get_builds,
            "/api/runs/latest": self._get_latest_run,
            "/api/package/artifact": self._get_package_artifact,
            "/api/package/archive": self._get_package_archive,
            "/api/showcase/paint": self._get_paint_showcase,
            "/api/showcase/paint/artifact": self._get_paint_showcase_artifact,
            "/api/showcase/paint/archive": self._get_paint_showcase_archive,
        }
        handler = routes.get(parsed.path)
        if handler:
            handler(parsed)
            return True
        if parsed.path.startswith("/api/builds/"):
            self._get_build_by_id(parsed)
            return True
        return False

    def _dispatch_post(self, path: str, payload: dict[str, Any]) -> bool:
        current_routes = {
            "/api/models/create": self._post_model_create,
            "/api/models/open": self._post_model_open,
            "/api/models/rename": self._post_model_rename,
            "/api/models/delete": self._post_model_delete,
            "/api/models/publish": self._post_model_publish,
            "/api/input-agent/message": self._post_input_agent_message,
            "/api/review-agent/message": self._post_review_agent_message,
            "/api/model/spec/generate": self._post_model_spec_generate,
            "/api/model/spec/approve": self._post_model_spec_approve,
            "/api/model/build": self._post_model_build,
            "/api/model/amend": self._post_model_amend,
            "/api/showcase/paint/rerun": self._post_paint_showcase_rerun,
        }
        legacy_routes = {
            "/api/run": self._post_run,
        }
        handler = current_routes.get(path) or legacy_routes.get(path)
        if not handler:
            return False
        handler(payload)
        return True

    def _get_health(self, _parsed) -> None:
        self._send_json({"ok": True, "server": "ModelFactoryLocal"})

    def _get_workspace(self, parsed) -> None:
        model_id = self._query_params(parsed).get("model_id")
        self._send_json(model_loop.build_workspace_payload(model_id))

    def _get_models(self, _parsed) -> None:
        self._send_json(model_loop.list_models_payload())

    def _get_builds(self, parsed) -> None:
        model_id = self._query_params(parsed).get("model_id")
        self._send_json({"builds": model_loop.list_model_builds(model_id)})

    def _get_build_by_id(self, parsed) -> None:
        run_id = parsed.path.rsplit("/", 1)[-1]
        build = model_loop.read_build(run_id)
        if not build:
            self._send_json({"error": "Build not found"}, status=HTTPStatus.NOT_FOUND)
            return
        self._send_json(build)

    def _get_latest_run(self, parsed) -> None:
        model_id = self._query_params(parsed).get("model_id")
        latest = model_loop.read_latest_run(model_id)
        self._send_json({"run": latest, "openai_called": False})

    def _get_package_artifact(self, parsed) -> None:
        params = self._query_params(parsed)
        self._send_json(model_loop.read_package_artifact(params.get("model_id", ""), params.get("path", "")))

    def _get_package_archive(self, parsed) -> None:
        params = self._query_params(parsed)
        payload = model_loop.build_package_archive(params.get("model_id", ""))
        self._send_bytes(payload["content"], content_type="application/zip", filename=payload["filename"])

    def _get_paint_showcase(self, _parsed) -> None:
        self._send_json(paint_showcase.read_showcase())

    def _get_paint_showcase_artifact(self, parsed) -> None:
        path = self._query_params(parsed).get("path", "")
        self._send_json(paint_showcase.read_model_file(path))

    def _get_paint_showcase_archive(self, _parsed) -> None:
        payload = paint_showcase.build_archive()
        self._send_bytes(payload["content"], content_type="application/zip", filename=payload["filename"])

    # /api/run remains for regular-mode reruns from the current frontend.
    def _post_run(self, payload: dict[str, Any]) -> None:
        self._send_json(
            model_loop.execute_run(
                input_params=payload.get("input_params") or {},
                build_run_id=payload.get("build_run_id"),
                change_intent=payload.get("change_intent"),
                model_id=payload.get("model_id"),
            )
        )

    def _post_model_create(self, payload: dict[str, Any]) -> None:
        self._send_json(model_loop.create_model_record(name=str(payload.get("name", "")), description=str(payload.get("description", ""))))

    def _post_model_open(self, payload: dict[str, Any]) -> None:
        self._send_json(model_loop.open_model_workspace(str(payload.get("model_id", ""))))

    def _post_model_delete(self, payload: dict[str, Any]) -> None:
        self._send_json(model_loop.delete_model_record(str(payload.get("model_id", ""))))

    def _post_model_rename(self, payload: dict[str, Any]) -> None:
        self._send_json(model_loop.rename_model_record(str(payload.get("model_id", "")), str(payload.get("name", ""))))

    def _post_model_publish(self, payload: dict[str, Any]) -> None:
        self._send_json(model_loop.publish_model_record(str(payload.get("model_id", ""))))

    def _post_input_agent_message(self, payload: dict[str, Any]) -> None:
        self._send_json(model_loop.send_input_agent_message_record(str(payload.get("model_id", "")), str(payload.get("message", ""))))

    def _post_review_agent_message(self, payload: dict[str, Any]) -> None:
        self._send_json(
            model_loop.send_review_agent_message_record(
                str(payload.get("model_id", "")),
                str(payload.get("message", "")),
                str(payload.get("phase", "review")),
            )
        )

    def _post_paint_showcase_rerun(self, payload: dict[str, Any]) -> None:
        self._send_json(paint_showcase.rerun_showcase(payload.get("inputs")))

    def _post_model_spec_generate(self, payload: dict[str, Any]) -> None:
        self._send_json(
            model_loop.generate_model_spec_record(
                str(payload.get("model_id", "")),
                str(payload.get("prompt", "")),
            )
        )

    def _post_model_spec_approve(self, payload: dict[str, Any]) -> None:
        spec = payload.get("model_spec")
        self._send_json(
            model_loop.approve_model_spec_record(
                str(payload.get("model_id", "")),
                spec if isinstance(spec, dict) else None,
            )
        )

    def _post_model_build(self, payload: dict[str, Any]) -> None:
        self._send_json(
            model_loop.build_model_package_record(
                str(payload.get("model_id", "")),
                str(payload.get("prompt", "")),
                openai_backed=payload.get("openai_backed", True) is not False,
            )
        )

    def _post_model_amend(self, payload: dict[str, Any]) -> None:
        self._send_json(
            model_loop.amend_model_package_record(
                str(payload.get("model_id", "")),
                str(payload.get("message", "")),
            )
        )

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        if length == 0:
            return {}
        raw = self.rfile.read(length).decode("utf-8")
        return json.loads(raw)

    def _query_params(self, parsed) -> dict[str, str]:
        pairs = {}
        for part in parsed.query.split("&"):
            if not part:
                continue
            key, _, value = part.partition("=")
            pairs[unquote(key)] = unquote(value)
        return pairs

    def _serve_frontend(self, raw_path: str) -> None:
        if not (FRONTEND_DIST_DIR / "index.html").exists():
            self._send_json(
                {"error": "Frontend build missing. Run `cd frontend; npm run build` before starting the Python server."},
                status=HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        root_dir = FRONTEND_DIST_DIR
        relative_path = raw_path.lstrip("/") or "index.html"
        resolved_root = root_dir.resolve()
        file_path = (resolved_root / relative_path).resolve()
        if not file_path.is_relative_to(resolved_root):
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return
        if not file_path.exists() and root_dir == FRONTEND_DIST_DIR:
            file_path = (root_dir / "index.html").resolve()
        if not file_path.exists():
            self._send_json({"error": "Not found"}, status=HTTPStatus.NOT_FOUND)
            return
        content_type = {
            ".html": "text/html; charset=utf-8",
            ".css": "text/css; charset=utf-8",
            ".js": "application/javascript; charset=utf-8",
            ".json": "application/json; charset=utf-8",
            ".svg": "image/svg+xml",
            ".ico": "image/x-icon",
            ".map": "application/json; charset=utf-8",
            ".woff2": "font/woff2",
        }.get(file_path.suffix, "application/octet-stream")
        content = file_path.read_bytes()
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.end_headers()
        self.wfile.write(content)

    def _send_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_bytes(self, body: bytes, *, content_type: str, filename: str) -> None:
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_api_error(self, exc: Exception) -> None:
        message = str(exc)
        status = HTTPStatus.INTERNAL_SERVER_ERROR
        payload: dict[str, Any] = {"error": message, "code": "server_error"}
        if message.startswith("Model not found:"):
            model_id = message.split(":", 1)[1].strip()
            status = HTTPStatus.NOT_FOUND
            payload = {"error": "Model not found", "model_id": model_id, "code": "model_not_found"}
        elif message == "Artifact not found.":
            status = HTTPStatus.NOT_FOUND
            payload = {"error": "Artifact not found", "code": "artifact_not_found"}
        elif "OPENAI_API_KEY is required" in message or "requires OPENAI_API_KEY" in message:
            status = HTTPStatus.SERVICE_UNAVAILABLE
            payload = {"error": message, "code": "openai_api_key_required"}
        elif message.startswith("Submitted inputs do not match this model's input schema."):
            status = HTTPStatus.BAD_REQUEST
            payload = {"error": message, "code": "invalid_run_inputs"}
        elif isinstance(exc, (ValueError, json.JSONDecodeError)):
            status = HTTPStatus.BAD_REQUEST
            payload = {"error": message, "code": "bad_request"}
        self._send_json(payload, status=status)


def create_server(host: str, port: int) -> ThreadingHTTPServer:
    return ThreadingHTTPServer((host, port), ModelFactoryHandler)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Model Factory local prototype.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()

    server = create_server(args.host, args.port)
    print(f"Serving Model Factory local prototype at http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
