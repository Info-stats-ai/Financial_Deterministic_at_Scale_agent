"""Minimal operator console backed by the live in-process session."""

from __future__ import annotations

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

from interface_ai.core.session import (
    ControlOwner,
    InvalidControlTransition,
    SessionManager,
)


def create_operator_app(session: SessionManager) -> FastAPI:
    app = FastAPI(title="Computer-Use Operator Console")

    @app.get("/", response_class=HTMLResponse)
    async def console() -> str:
        return """<!doctype html>
<html><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Operator Console</title><style>
body{font:16px system-ui;background:#0f172a;color:#e2e8f0;margin:0;padding:32px}
main{max-width:760px;margin:auto}.card{background:#1e293b;padding:24px;border-radius:16px}
.pill{display:inline-block;padding:6px 10px;background:#334155;border-radius:999px}
button{font:inherit;font-weight:700;padding:12px 18px;margin:12px 8px 0 0;border:0;
border-radius:10px;cursor:pointer}.take{background:#f59e0b}.resume{background:#22c55e}
pre{white-space:pre-wrap;background:#0f172a;padding:16px;border-radius:10px}
</style></head><body><main><h1>Live-session handoff</h1><div class="card">
<p>Control owner: <strong id="owner" class="pill">loading</strong></p>
<pre id="context">Waiting for intervention…</pre>
<button class="take" onclick="post('/api/take-control')">Take control</button>
<button class="resume" onclick="post('/api/resume')">Resume automation</button>
</div></main><script>
async function refresh(){const r=await fetch('/api/state');const s=await r.json();
owner.textContent=s.owner;context.textContent=JSON.stringify(s.intervention,null,2)}
async function post(path){const r=await fetch(path,{method:'POST'});
if(!r.ok)alert(await r.text());await refresh()}setInterval(refresh,1000);refresh();
</script></body></html>"""

    @app.get("/api/state")
    async def state() -> dict[str, object]:
        return {
            "owner": session.owner.value,
            "intervention": (
                session.intervention.model_dump(mode="json") if session.intervention else None
            ),
            "human_action_count": len(session.human_actions),
        }

    @app.post("/api/take-control")
    async def take_control() -> dict[str, str]:
        try:
            await session.take_control()
        except InvalidControlTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"owner": ControlOwner.HUMAN.value}

    @app.post("/api/resume")
    async def resume() -> dict[str, str]:
        try:
            await session.resume_automation()
        except InvalidControlTransition as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        return {"owner": ControlOwner.AUTOMATION.value}

    return app
