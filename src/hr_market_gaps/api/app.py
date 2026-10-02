from __future__ import annotations

from pathlib import Path

from ..runtime import CaseNotRunnableError, CaseRunner
from ..version import __version__


def create_app(repo_root: str | Path = "."):
    """Create the optional FastAPI surface without making FastAPI a core dependency."""

    try:
        from fastapi import FastAPI, HTTPException
    except ImportError as exc:  # pragma: no cover - optional dependency
        raise RuntimeError("Install the 'api' extra to use the local API") from exc

    runner = CaseRunner(repo_root)
    app = FastAPI(title="HR Market Gaps Engine", version=__version__)

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/cases")
    def cases() -> list[dict]:
        return [entry.model_dump(mode="json") for entry in runner.list_cases(visible_only=True)]

    @app.post("/cases/{case_id}/run")
    def run_case(case_id: str) -> dict:
        try:
            return runner.run(case_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown case") from exc
        except CaseNotRunnableError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    return app
