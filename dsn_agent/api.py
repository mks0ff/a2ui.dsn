import asyncio
import logging
from uuid import uuid4

from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware

from .config import ROOT, Settings
from .errors import AnalysisError
from .presentation import Presenter
from .prompts import Visualization, load_prompts
from .results import ResultStore

logger = logging.getLogger(__name__)


class AnalysisRequest(BaseModel):
    question: str = Field(min_length=1, max_length=4000)
    visualization: Visualization = "auto"


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or Settings()
    app = FastAPI(title="DSN Analytics", version="0.1.0")
    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=["localhost", "127.0.0.1", "testserver"]
    )
    store = ResultStore()
    presenter = Presenter()
    app.state.store = store
    app.state.runtime = None
    app.state.owners = set()
    runtime_lock = asyncio.Lock()

    @app.middleware("http")
    async def local_origin(request: Request, call_next):
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            origin = request.headers.get("origin")
            allowed = {
                f"http://{host}:{port}"
                for host in ("localhost", "127.0.0.1")
                for port in (5173, 8000)
            }
            if origin and origin not in allowed:
                return JSONResponse(
                    status_code=403,
                    content={"code": "invalid_origin", "message": "Origine locale non autorisee."},
                )
        return await call_next(request)

    @app.exception_handler(AnalysisError)
    async def analysis_error(request: Request, exc: AnalysisError):
        return JSONResponse(
            status_code=exc.status, content={"code": exc.code, "message": exc.message}
        )

    @app.exception_handler(Exception)
    async def unexpected_error(request: Request, exc: Exception):
        logger.exception("DSN request failed: %s", request.url.path, exc_info=exc)
        return JSONResponse(
            status_code=500,
            content={
                "code": "server_error",
                "message": "Erreur du serveur. Consultez le journal Python ; aucune analyse fabriquee.",
            },
        )

    def owner(request: Request) -> str:
        identity = request.cookies.get("dsn_session")
        if identity not in app.state.owners:
            raise AnalysisError("Ouvrez une nouvelle conversation.", "session_expired", 401)
        return identity

    async def runtime():
        async with runtime_lock:
            if app.state.runtime is None:
                from google.auth.exceptions import GoogleAuthError

                from .agent import DsnAgent

                try:
                    app.state.runtime = await asyncio.to_thread(DsnAgent, settings, store)
                except GoogleAuthError as exc:
                    raise AnalysisError(
                        "ADC indisponibles. Configurez l'authentification Google Cloud "
                        f"cote serveur : {exc}",
                        "authentication_required",
                        503,
                    ) from exc
            return app.state.runtime

    @app.get("/api/health")
    def health():
        return {
            "status": "configured" if not settings.missing else "configuration_required",
            "missing": settings.missing,
            "limits": {
                "bytes_billed": settings.max_bytes_billed,
                "rows": settings.max_result_rows,
                "chart_points": settings.max_chart_points,
                "sql_attempts": settings.max_sql_attempts,
            },
        }

    @app.get("/api/prompts")
    def prompts():
        try:
            return [entry.model_dump() for entry in load_prompts(settings.prompt_file)]
        except (ValueError, OSError) as exc:
            raise AnalysisError(
                f"Catalogue de suggestions invalide : {exc}", "prompt_config_error", 500
            ) from exc

    @app.post("/api/session")
    def session(request: Request, response: Response):
        identity = request.cookies.get("dsn_session")
        if identity not in app.state.owners:
            identity = str(uuid4())
            app.state.owners.add(identity)
        response.set_cookie("dsn_session", identity, httponly=True, samesite="strict")
        return {"status": "ready"}

    @app.post("/api/analyze")
    async def analyze(body: AnalysisRequest, identity: str = Depends(owner)):
        if not body.question.strip():
            raise AnalysisError("La question est vide.", "empty_question")
        agent = await runtime()
        turn, text = await agent.analyze(identity, body.question.strip(), body.visualization)
        return {
            "text": text,
            "status": "result" if turn.result else "clarification",
            "warnings": turn.errors,
            "presentation": (
                presenter.render(turn.result, body.visualization, settings.max_chart_points)
                if turn.result
                else None
            ),
        }

    @app.get("/api/results/{result_id}")
    def result(
        result_id: str, visualization: Visualization = "auto", identity: str = Depends(owner)
    ):
        return presenter.render(
            store.get(identity, result_id), visualization, settings.max_chart_points
        )

    @app.get("/api/results/{result_id}/rows")
    def rows(
        result_id: str,
        offset: int = Query(default=0, ge=0),
        limit: int = Query(default=50, ge=1, le=200),
        identity: str = Depends(owner),
    ):
        result = store.get(identity, result_id)
        return {
            "rows": result.rows[offset : offset + limit],
            "total": len(result.rows),
            "offset": offset,
            "limit": limit,
        }

    @app.delete("/api/session")
    async def clear(response: Response, identity: str = Depends(owner)):
        if app.state.runtime is not None:
            await app.state.runtime.clear(identity)
        store.clear(identity)
        app.state.owners.discard(identity)
        response.delete_cookie("dsn_session")
        return {"status": "cleared", "notice": "L'historique Google Cloud n'est pas supprime."}

    dist = ROOT / "frontend" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="frontend")
    return app


app = create_app()
