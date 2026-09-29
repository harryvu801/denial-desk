"""FastAPI application: the review queue, the review action, and the audit log.

Server-rendered (ADR-001, ADR-025): the screen exists so a human can approve, override or
reject every proposal. Nothing here submits a claim or an appeal to anyone (ADR-007).

Run with `uvicorn denial_desk.api.main:create_app --factory` so importing this module
never opens a database.
"""

from __future__ import annotations

from collections.abc import Iterator
from decimal import Decimal
from pathlib import Path
from typing import Annotated

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from denial_desk.config import settings
from denial_desk.domain.models import Payer, ResolutionPath
from denial_desk.persistence.models import DenialRow
from denial_desk.persistence.store import (
    ReviewAction,
    get_denial,
    list_denials,
    make_engine,
    queue_stats,
    recent_audit,
    review,
    session_scope,
)
from denial_desk.reference import carc_table, payer_rules, rarc_table

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")
TEMPLATES.env.filters["money"] = lambda v: f"${Decimal(v):,.2f}"


def get_session(request: Request) -> Iterator[Session]:
    """One transaction per request: committed if the handler returns, rolled back if it raises."""
    db_engine: Engine = request.app.state.engine
    with session_scope(db_engine) as session:
        yield session


# Module level, not inside create_app: with `from __future__ import annotations` FastAPI
# resolves annotations by name from module globals, so a local alias is invisible to it.
SessionDep = Annotated[Session, Depends(get_session)]


def create_app(database_url: str | None = None) -> FastAPI:
    engine = make_engine(database_url or settings.database_url)
    app = FastAPI(title="Denial Desk", version="0.1.0")
    app.state.engine = engine

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def queue(
        request: Request,
        session: SessionDep,
        status: str = "pending",
        lane: str = "",
        payer: str = "",
    ) -> HTMLResponse:
        rows = list_denials(session, status=status or None, lane=lane or None, payer=payer or None)
        return TEMPLATES.TemplateResponse(
            request,
            "queue.html",
            {
                "rows": rows,
                "stats": queue_stats(session),
                "filters": {"status": status, "lane": lane, "payer": payer},
                "payers": [p.value for p in Payer],
            },
        )

    @app.get("/denials/{denial_id}", response_class=HTMLResponse)
    def detail(request: Request, denial_id: int, session: SessionDep) -> HTMLResponse:
        row = get_denial(session, denial_id)
        if row is None:
            raise HTTPException(404, "denial not found")
        as_of = row.adjudication_date
        codes = [(row.primary_carc, carc_table().describe(row.primary_carc, as_of))]
        remarks = [
            (code, rarc_table().describe(code, as_of))
            for code in row.remark_codes.split(",")
            if code
        ]
        return TEMPLATES.TemplateResponse(
            request,
            "detail.html",
            {
                "row": row,
                "rec": row.record,
                "carcs": codes,
                "rarcs": remarks,
                "payer_rules": payer_rules()[row.payer],
                "paths": [p for p in ResolutionPath if p is not ResolutionPath.NEEDS_HUMAN],
            },
        )

    @app.post("/denials/{denial_id}/review")
    def submit_review(
        denial_id: int,
        session: SessionDep,
        action: Annotated[ReviewAction, Form()],
        note: Annotated[str, Form()] = "",
        override_path: Annotated[str, Form()] = "",
    ) -> RedirectResponse:
        try:
            review(
                session,
                denial_id,
                action,
                reviewer=settings.reviewer_name,
                note=note,
                override_path=ResolutionPath(override_path) if override_path else None,
            )
        except LookupError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        session.flush()
        next_id = session.scalar(
            select(DenialRow.id)
            .where(DenialRow.status == "pending")
            .order_by(DenialRow.denied_amount.desc(), DenialRow.id)
            .limit(1)
        )
        return RedirectResponse(f"/denials/{next_id}" if next_id else "/", status_code=303)

    @app.get("/audit", response_class=HTMLResponse)
    def audit(request: Request, session: SessionDep) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(request, "audit.html", {"events": recent_audit(session)})

    return app
