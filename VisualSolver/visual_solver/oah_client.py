"""
OAH (Open Agent Harness) Workspace Client for VisualSolver.

Synchronous implementation using urllib (standard library) to avoid
event loop conflicts with LiteLLM's aiohttp in the same process.
"""

import json
import os
import time
import urllib.request
import urllib.error
import urllib.parse
from typing import Optional
from io import BytesIO
from PIL import Image


def _log(msg: str):
    print(f"[OAH] {msg}", flush=True)


class OAHClient:
    """Synchronous client for OAH Workspace API (urllib-based)."""

    def __init__(
        self,
        api_url: Optional[str] = None,
        token: Optional[str] = None,
        workspace_template: str = "visual-solver-code",
        timeout: float = 1200.0,
        model_ref: Optional[str] = None,
        cleanup: bool = True,
    ):
        self.api_url = api_url or os.getenv("OAH_API_URL", "")
        if not self.api_url:
            raise ValueError("OAH_API_URL is required (pass api_url or set env var)")
        self.token = token or os.getenv("OAH_TOKEN", "") or os.getenv("OAH_LOCAL_API_TOKEN", "")
        self.workspace_template = workspace_template
        self.timeout = timeout
        self.model_ref = model_ref
        self.cleanup = cleanup

    def _request(self, method: str, path: str, body: Optional[bytes] = None,
                 headers: Optional[dict] = None, params: Optional[dict] = None) -> dict:
        """Send an HTTP request and return parsed JSON response."""
        url = f"{self.api_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Accept", "application/json")
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")
        if body is not None:
            if headers and "Content-Type" in headers:
                req.add_header("Content-Type", headers["Content-Type"])
            else:
                req.add_header("Content-Type", "application/json")

        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                data = resp.read().decode("utf-8")
                if data:
                    return json.loads(data)
                return {}
        except urllib.error.HTTPError as e:
            body_text = e.read().decode("utf-8", errors="replace")
            raise RuntimeError(f"OAH API error: {e.code} {e.reason} — {body_text[:500]}")
        except urllib.error.URLError as e:
            raise RuntimeError(f"OAH connection error: {e.reason}")

    def _request_raw(self, method: str, path: str, body: Optional[bytes] = None,
                     headers: Optional[dict] = None, params: Optional[dict] = None) -> bytes:
        """Send an HTTP request and return raw response bytes."""
        url = f"{self.api_url}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)

        req = urllib.request.Request(url, data=body, method=method)
        if headers:
            for k, v in headers.items():
                req.add_header(k, v)
        if self.token:
            req.add_header("Authorization", f"Bearer {self.token}")

        with urllib.request.urlopen(req, timeout=self.timeout) as resp:
            return resp.read()

    # ── Workspace ──────────────────────────────────────────────────────────

    def create_workspace(self, name: str) -> str:
        data = self._request("POST", "/api/v1/workspaces",
                             body=json.dumps({"name": name, "runtime": self.workspace_template}).encode())
        ws_id = data["id"]
        _log(f"Created workspace: {ws_id}")
        return ws_id

    def delete_workspace(self, workspace_id: str) -> None:
        try:
            self._request("DELETE", f"/api/v1/workspaces/{workspace_id}")
            _log(f"Deleted workspace: {workspace_id}")
        except Exception as e:
            _log(f"Failed to delete workspace {workspace_id}: {e}")

    def delete_workspace_immediately(self, workspace_id: str) -> None:
        """Delete workspace immediately after use.

        Previous implementation used a 2-hour delayed daemon thread, but since
        the Python process typically exits before the timer fires, workspaces
        were never cleaned up, eventually exhausting inotify watchers and
        crashing the OAH server.
        """
        _log(f"Deleting workspace {workspace_id}...")
        self.delete_workspace(workspace_id)

    # ── Session ────────────────────────────────────────────────────────────

    def create_session(
        self,
        workspace_id: str,
        title: str = "Scene generation",
        agent_name: Optional[str] = None,
        model_ref: Optional[str] = None,
    ) -> str:
        effective_model = model_ref or self.model_ref
        body: dict = {"title": title}
        if agent_name:
            body["agentName"] = agent_name
        if effective_model:
            body["modelRef"] = effective_model
        data = self._request("POST", f"/api/v1/workspaces/{workspace_id}/sessions",
                             body=json.dumps(body).encode())
        ses_id = data["id"]
        _log(f"Created session: {ses_id}" +
             (f" agent={agent_name}" if agent_name else "") +
             (f" model={effective_model}" if effective_model else ""))
        return ses_id

    def update_session(
        self,
        session_id: str,
        active_agent_name: Optional[str] = None,
        model_ref: Optional[str] = None,
        title: Optional[str] = None,
    ) -> dict:
        body: dict = {}
        if title is not None:
            body["title"] = title
        if active_agent_name is not None:
            body["activeAgentName"] = active_agent_name
        if model_ref is not None:
            body["modelRef"] = model_ref
        return self._request("PATCH", f"/api/v1/sessions/{session_id}",
                             body=json.dumps(body).encode())

    # ── Messages & Runs ────────────────────────────────────────────────────

    def send_message(self, session_id: str, content: str) -> str:
        data = self._request("POST", f"/api/v1/sessions/{session_id}/messages",
                             body=json.dumps({"content": content}).encode())
        run_id = data["runId"]
        _log(f"Sent message, run={run_id}")
        return run_id

    def send_multimodal_message(self, session_id: str, content_parts: list) -> str:
        """Send a multimodal message with text and/or image parts.

        content_parts: list of dicts, e.g.
            [{"type": "text", "text": "..."}, {"type": "image", "image": "<base64>", "mediaType": "image/png"}]
        """
        data = self._request("POST", f"/api/v1/sessions/{session_id}/messages",
                             body=json.dumps({"content": content_parts}).encode())
        run_id = data["runId"]
        _log(f"Sent multimodal message, run={run_id}")
        return run_id

    def wait_for_run(self, run_id: str, max_seconds: int = 600, poll_interval: float = 2.0) -> dict:
        """Wait for a run to complete and return a dict with status and usage.

        Returns:
            dict with keys:
                status: "completed" | "failed" | "cancelled"
                usage: {"inputTokens": int, "outputTokens": int, "totalTokens": int} | {}
        """
        start = time.monotonic()
        last_status = ""
        run = {}
        while time.monotonic() - start < max_seconds:
            try:
                run = self._request("GET", f"/api/v1/runs/{run_id}")
                status = run.get("status", "")
                if status != last_status:
                    _log(f"Run {run_id} status: {status} ({time.monotonic()-start:.0f}s)")
                    last_status = status
                if status in ("completed", "failed", "cancelled"):
                    return {
                        "status": status,
                        "usage": run.get("usage", {}),
                    }
            except Exception as e:
                _log(f"Run poll error ({time.monotonic()-start:.0f}s): {e}")
            time.sleep(poll_interval)
        raise TimeoutError(f"[OAH] Run {run_id} did not finish within {max_seconds}s")

    def init_session(self, session_id: str) -> None:
        _log("Initializing session (materialize workspace)...")
        run_id = self.send_message(
            session_id,
            "初始化会话，暂时不要调用任何工具，只需回复【已就绪】。",
        )
        result = self.wait_for_run(run_id, max_seconds=int(self.timeout))
        if result["status"] != "completed":
            raise RuntimeError(f"Session init run ended with status: {result['status']}")
        _log("Session initialized")

    # ── File Upload / Read / Download ──────────────────────────────────────

    def upload_file(self, workspace_id: str, local_path: str, workspace_path: str) -> None:
        with open(local_path, "rb") as f:
            content = f.read()
        self.upload_buffer(workspace_id, content, workspace_path)

    def upload_buffer(self, workspace_id: str, data: bytes, workspace_path: str) -> None:
        try:
            self._request("PUT", f"/api/v1/sandboxes/{workspace_id}/files/upload",
                          body=data,
                          headers={"Content-Type": "application/octet-stream"},
                          params={"path": workspace_path, "overwrite": "true"})
        except Exception as e:
            _log(f"Upload failed for {workspace_path}: {e}")
            raise

    def upload_json(self, workspace_id: str, obj: dict, workspace_path: str) -> None:
        self.upload_buffer(
            workspace_id,
            json.dumps(obj, ensure_ascii=False, indent=2).encode("utf-8"),
            workspace_path,
        )

    def upload_image(self, workspace_id: str, img: Image.Image, workspace_path: str) -> None:
        buf = BytesIO()
        img.save(buf, format="PNG")
        self.upload_buffer(workspace_id, buf.getvalue(), workspace_path)

    def read_file_text(self, workspace_id: str, workspace_path: str, retries: int = 10) -> str:
        for attempt in range(retries):
            try:
                data = self._request("GET", f"/api/v1/sandboxes/{workspace_id}/files/content",
                                     params={"path": workspace_path})
                content = data.get("content", "")
                if content and content.strip():
                    return content
            except Exception:
                pass
            if attempt < retries - 1:
                _log(f"File {workspace_path} not ready, retry {attempt+1}/{retries}...")
                time.sleep(3)
        raise RuntimeError(f"Failed to read {workspace_path} after {retries} attempts")

    def download_file(self, workspace_id: str, workspace_path: str) -> bytes:
        return self._request_raw("GET", f"/api/v1/sandboxes/{workspace_id}/files/download",
                                params={"path": workspace_path})

    def wait_for_file(self, workspace_id: str, workspace_path: str, max_seconds: int = 180) -> None:
        start = time.monotonic()
        while time.monotonic() - start < max_seconds:
            try:
                data = self._request("GET", f"/api/v1/sandboxes/{workspace_id}/files/content",
                              params={"path": workspace_path})
                content = data.get("content", "")
                if content and content.strip():
                    _log(f"File synced: {workspace_path} ({time.monotonic()-start:.1f}s)")
                    return
            except Exception:
                pass
            time.sleep(3)
        _log(f"File sync timeout: {workspace_path}")

    # ── High-level: generate scene HTML via OAH ────────────────────────────

    def _upload_problem_image(self, workspace_id: str, problem_image: Image.Image,
                               spec: dict, img_filename: str = "topic.png") -> None:
        """Upload problem image to workspace and add img_file to spec dict."""
        self.upload_image(workspace_id, problem_image, img_filename)
        spec["img_file"] = img_filename

    def generate_scene_html(
        self,
        spec: dict,
        output_file: str = "scene.html",
        problem_image: Optional[Image.Image] = None,
    ) -> dict:
        """Full pipeline: create workspace -> upload spec -> send message -> read output file.

        Returns:
            dict with keys:
                html: str — the generated HTML content
                usage: {"inputTokens": int, "outputTokens": int, "totalTokens": int}
        """
        workspace_id = None
        try:
            _log(f"Step 1: Creating workspace...")
            ws_name = f"vs-{spec.get('topic', 'scene')}-{spec.get('scene_number', 0)}-{int(time.time())}"
            workspace_id = self.create_workspace(ws_name)

            _log(f"Step 2: Creating session...")
            session_id = self.create_session(
                workspace_id, title=f"Scene {spec.get('scene_number', '?')} generation"
            )

            _log(f"Step 3: Initializing session...")
            self.init_session(session_id)

            _log(f"Step 4: Uploading spec.json...")
            if problem_image is not None:
                self._upload_problem_image(workspace_id, problem_image, spec)
            self.upload_json(workspace_id, spec, "spec.json")

            _log(f"Step 5: Waiting for file sync...")
            self.wait_for_file(workspace_id, "spec.json")
            if spec.get("img_file"):
                self.wait_for_file(workspace_id, spec["img_file"])

            _log(f"Step 6: Sending generation message for {output_file}...")
            msg = (
                f"请读取 spec.json，根据规格生成完整的 HTML 场景文件，"
                f"写入 {output_file}。完成后立即结束。"
            )
            run_id = self.send_message(session_id, msg)

            _log(f"Step 7: Waiting for agent run (timeout={self.timeout}s)...")
            result = self.wait_for_run(run_id, max_seconds=int(self.timeout))
            if result["status"] != "completed":
                raise RuntimeError(f"Agent run ended with status: {result['status']}")

            _log(f"Step 8: Reading {output_file}...")
            html = self.read_file_text(workspace_id, output_file, retries=5)
            if not html or not html.strip():
                raise ValueError(f"{output_file} is empty after agent run")

            _log(f"Got {output_file}: {len(html)} chars")
            return {"html": html, "usage": result["usage"]}

        finally:
            if self.cleanup and workspace_id:
                self.delete_workspace_immediately(workspace_id)

    # ── High-level: modify scene HTML via OAH ─────────────────────────────

    def modify_scene_html(
        self,
        spec: dict,
        current_code: str,
        output_file: str = "modified_scene.html",
        problem_image: Optional[Image.Image] = None,
    ) -> dict:
        """Modify an existing scene HTML via OAH code agent.

        spec should contain:
            task: "modify_scene"
            topic, scene_number, user_request, problem_text (optional)
        current_code: the existing HTML to be modified

        Returns:
            dict with keys:
                html: str — the modified HTML content
                usage: {"inputTokens": int, "outputTokens": int, "totalTokens": int}
        """
        import base64

        workspace_id = None
        try:
            _log(f"Step 1: Creating modify workspace...")
            ws_name = f"vm-{spec.get('topic', 'modify')}-{spec.get('scene_number', 0)}-{int(time.time())}"
            workspace_id = self.create_workspace(ws_name)

            _log(f"Step 2: Creating session...")
            session_id = self.create_session(
                workspace_id, title=f"Scene {spec.get('scene_number', '?')} modification"
            )

            _log(f"Step 3: Initializing session...")
            self.init_session(session_id)

            _log(f"Step 4: Uploading spec.json + current_scene.html...")
            self.upload_json(workspace_id, spec, "spec.json")
            self.upload_buffer(
                workspace_id,
                current_code.encode("utf-8"),
                "current_scene.html",
            )

            _log(f"Step 5: Waiting for file sync...")
            self.wait_for_file(workspace_id, "spec.json")
            self.wait_for_file(workspace_id, "current_scene.html")

            _log(f"Step 6: Sending modification message...")
            msg_text = (
                f"请读取 spec.json 和 current_scene.html，根据修改需求修改代码，"
                f"将修改后的完整 HTML 写入 {output_file}。完成后立即结束。"
            )

            if problem_image is not None:
                buf = BytesIO()
                problem_image.save(buf, format="PNG")
                img_b64 = base64.b64encode(buf.getvalue()).decode("ascii")
                content_parts = [
                    {"type": "text", "text": msg_text},
                    {"type": "image", "image": img_b64, "mediaType": "image/png"},
                ]
                run_id = self.send_multimodal_message(session_id, content_parts)
            else:
                run_id = self.send_message(session_id, msg_text)

            _log(f"Step 7: Waiting for modify run (timeout=1200s)...")
            result = self.wait_for_run(run_id, max_seconds=1200)
            if result["status"] != "completed":
                raise RuntimeError(f"Modify run ended with status: {result['status']}")

            _log(f"Step 8: Reading {output_file}...")
            html = self.read_file_text(workspace_id, output_file, retries=5)
            if not html or not html.strip():
                raise ValueError(f"{output_file} is empty after modify run")

            _log(f"Got {output_file}: {len(html)} chars")
            return {"html": html, "usage": result["usage"]}

        finally:
            if self.cleanup and workspace_id:
                self.delete_workspace_immediately(workspace_id)

    # ── High-level: generate scene outline via OAH ──────────────────────

    def generate_scene_outline(
        self,
        spec: dict,
        problem_image: Optional[Image.Image] = None,
        output_file: str = "scene_outline.txt",
    ) -> dict:
        """Generate scene outline via OAH outline agent.

        Returns:
            dict with keys:
                outline: str — the generated outline text
                usage: {"inputTokens": int, "outputTokens": int, "totalTokens": int}
        """
        import base64

        workspace_id = None
        try:
            _log(f"Step 1: Creating outline workspace...")
            ws_name = f"vo-{spec.get('topic', 'outline')}-{int(time.time())}"
            orig_template = self.workspace_template
            self.workspace_template = "visual-solver-outline"
            try:
                workspace_id = self.create_workspace(ws_name)
            finally:
                self.workspace_template = orig_template

            _log(f"Step 2: Creating session...")
            session_id = self.create_session(
                workspace_id, title="Scene outline generation"
            )

            _log(f"Step 3: Initializing session...")
            self.init_session(session_id)

            _log(f"Step 4: Uploading spec.json...")
            if problem_image is not None:
                self._upload_problem_image(workspace_id, problem_image, spec)
            self.upload_json(workspace_id, spec, "spec.json")

            _log(f"Step 5: Waiting for file sync...")
            self.wait_for_file(workspace_id, "spec.json")
            if spec.get("img_file"):
                self.wait_for_file(workspace_id, spec["img_file"])

            _log(f"Step 6: Sending outline generation message...")
            msg_text = (
                f"请读取 spec.json"
                f"{'（含题目图片 img_file）' if spec.get('img_file') else ''}，"
                f"根据题目描述生成完整的教学图示大纲，"
                f"写入 {output_file}。完成后立即结束。"
            )
            run_id = self.send_message(session_id, msg_text)

            _log(f"Step 7: Waiting for outline run (timeout=1200s)...")
            result = self.wait_for_run(run_id, max_seconds=1200)
            if result["status"] != "completed":
                raise RuntimeError(f"Outline run ended with status: {result['status']}")

            _log(f"Step 8: Reading {output_file}...")
            outline = self.read_file_text(workspace_id, output_file, retries=5)
            if not outline or not outline.strip():
                raise ValueError(f"{output_file} is empty after outline run")

            _log(f"Got {output_file}: {len(outline)} chars")
            return {"outline": outline, "usage": result["usage"]}

        finally:
            if self.cleanup and workspace_id:
                self.delete_workspace_immediately(workspace_id)

    # ── High-level: generate implementation plan via OAH ──────────────────

    def generate_implementation_plan(
        self,
        spec: dict,
        problem_image: Optional[Image.Image] = None,
        output_file: str = "implementation_plan.txt",
    ) -> dict:
        """Generate scene implementation plan via OAH planner agent.

        Same pipeline as generate_scene_html but uses the visual-solver-plan
        runtime template and produces a text plan instead of HTML.

        Returns:
            dict with keys:
                plan: str — the generated implementation plan text
                usage: {"inputTokens": int, "outputTokens": int, "totalTokens": int}
        """
        workspace_id = None
        try:
            _log(f"Step 1: Creating planner workspace...")
            ws_name = f"vp-{spec.get('topic', 'plan')}-{spec.get('scene_number', 0)}-{int(time.time())}"
            # Temporarily switch template for this workspace
            orig_template = self.workspace_template
            self.workspace_template = "visual-solver-plan"
            try:
                workspace_id = self.create_workspace(ws_name)
            finally:
                self.workspace_template = orig_template

            _log(f"Step 2: Creating session...")
            session_id = self.create_session(
                workspace_id, title=f"Scene {spec.get('scene_number', '?')} planning"
            )

            _log(f"Step 3: Initializing session...")
            self.init_session(session_id)

            _log(f"Step 4: Uploading spec.json...")
            if problem_image is not None:
                self._upload_problem_image(workspace_id, problem_image, spec)
            self.upload_json(workspace_id, spec, "spec.json")

            _log(f"Step 5: Waiting for file sync...")
            self.wait_for_file(workspace_id, "spec.json")
            if spec.get("img_file"):
                self.wait_for_file(workspace_id, spec["img_file"])

            _log(f"Step 6: Sending planning message...")
            msg = (
                f"请读取 spec.json"
                f"{'（含题目图片 img_file）' if spec.get('img_file') else ''}，"
                f"根据场景大纲生成本场景的设计与实现计划，"
                f"写入 {output_file}。完成后立即结束。"
            )
            run_id = self.send_message(session_id, msg)

            _log(f"Step 7: Waiting for planner run (timeout=1200s)...")
            result = self.wait_for_run(run_id, max_seconds=1200)
            if result["status"] != "completed":
                raise RuntimeError(f"Planner run ended with status: {result['status']}")

            _log(f"Step 8: Reading {output_file}...")
            plan = self.read_file_text(workspace_id, output_file, retries=5)
            if not plan or not plan.strip():
                raise ValueError(f"{output_file} is empty after planner run")

            _log(f"Got {output_file}: {len(plan)} chars")
            return {"plan": plan, "usage": result["usage"]}

        finally:
            if self.cleanup and workspace_id:
                self.delete_workspace_immediately(workspace_id)
