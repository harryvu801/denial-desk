"""FastAPI application: the review queue, the review action, and the audit log.

Server-rendered (ADR-001, ADR-025): the screen exists so a human can approve, override or
reject every proposal. Nothing here submits a claim or an appeal to anyone (ADR-007).

Run with `uvicorn denial_desk.api.main:create_app --factory` so importing this module
never opens a database.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Annotated
from urllib.parse import urlencode, urlparse

from fastapi import Depends, FastAPI, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from denial_desk.config import settings
from denial_desk.domain.models import Payer, ResolutionPath
from denial_desk.persistence.models import DenialRow
from denial_desk.persistence.store import (
    SORT_COLUMNS,
    AlreadyDecidedError,
    ReviewAction,
    get_denial,
    list_denials,
    make_engine,
    model_cost,
    queue_stats,
    recent_audit,
    review,
    session_scope,
)
from denial_desk.reference import carc_table, payer_rules, rarc_table

TEMPLATES = Jinja2Templates(directory=Path(__file__).parent / "templates")
# Expiry on screen uses the real date: a deadline that was fine at ingest can pass while
# the item waits in the queue.
TEMPLATES.env.globals["today"] = date.today
TEMPLATES.env.filters["money"] = lambda v: f"${Decimal(v):,.2f}"
TEMPLATES.env.filters["num"] = lambda v: f"{v:,}"

# Display names for stored values. Stored values stay machine-friendly (snake_case, ADR
# vocabulary); the screen shows sentence-case labels. One place, so no template ever
# prints `corrected_claim`.
LABELS = {
    "deterministic": "Rules",
    "model": "Model",
    "human": "Human",
    "corrected_claim": "Corrected claim",
    "write_off": "Write-off",
    "no_action": "No action",
    "needs_human": "Needs human",
}
ABBREVIATIONS = {
    "CARC": "Claim Adjustment Reason Code: the payer's standard reason for not paying",
    "RARC": "Remittance Advice Remark Code: extra detail on the reason",
    "Proc": "Procedure code (HCPCS/CPT) as billed",
    "ICN": "Internal Control Number: the payer's own claim number",
    "EVV": "Electronic Visit Verification: the caregiver's recorded check-in and check-out",
    "PCN": "Patient Control Number: the provider's claim number (CLM01)",
}


def label(value: object) -> str:
    """`corrected_claim` -> `Corrected claim`; known terms map to their display name."""
    if value is None or value == "":
        return "—"
    text = str(value)
    return LABELS.get(text) or text.replace("_", " ")[:1].upper() + text.replace("_", " ")[1:]


TEMPLATES.env.filters["label"] = label


def actor(value: str) -> str:
    """`system` -> `Rules engine`, `model:claude-sonnet-5-5` -> `Model (claude-sonnet-5-5)`."""
    if value == "system":
        return "Rules engine"
    if value.startswith("model:"):
        return f"Model ({value.removeprefix('model:')})"
    return value[:1].upper() + value[1:]


TEMPLATES.env.filters["actor"] = actor
TEMPLATES.env.globals["abbr"] = ABBREVIATIONS
TEMPLATES.env.globals["carc_desc"] = lambda code, as_of: carc_table().describe(code, as_of)
TEMPLATES.env.globals["rarc_desc"] = lambda code, as_of: rarc_table().describe(code, as_of)

PAGE_SIZE = 50
FLASH_VERBS = {"approve": "Approved", "override": "Overrode", "reject": "Rejected the proposal for"}


def flash_message(done: str, outcome: str, *, next_item: bool) -> str | None:
    """Confirmation after a review, shown on the page the reviewer lands on."""
    if not done or outcome not in FLASH_VERBS:
        return None
    tail = " Next pending denial below." if next_item else " The queue is clear."
    return f"{FLASH_VERBS[outcome]} {done}.{tail}"


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
        q: str = "",
        sort: str = "denied",
        order: str = "desc",
        page: int = 1,
        done: str = "",
        outcome: str = "",
    ) -> HTMLResponse:
        sort = sort if sort in SORT_COLUMNS else "denied"
        page = max(page, 1)
        result = list_denials(
            session,
            status=status or None,
            lane=lane or None,
            payer=payer or None,
            search=q,
            sort=sort,
            descending=order != "asc",
            limit=PAGE_SIZE,
            offset=(page - 1) * PAGE_SIZE,
        )
        filters = {"status": status, "lane": lane, "payer": payer, "q": q}
        return TEMPLATES.TemplateResponse(
            request,
            "queue.html",
            {
                "active": "queue",
                "flash": flash_message(done, outcome, next_item=False),
                "rows": result.rows,
                "total": result.total,
                "page": page,
                "pages": max(1, -(-result.total // PAGE_SIZE)),
                "page_size": PAGE_SIZE,
                "stats": queue_stats(session),
                "model_cost": model_cost(session),
                "filters": filters,
                "sort": sort,
                "order": "asc" if order == "asc" else "desc",
                # Query string for links that change one thing and keep the rest.
                "base_query": urlencode(filters),
                "filtered": bool(lane or payer or q or status != "pending"),
                "payers": [p.value for p in Payer],
            },
        )

    @app.get("/denials/{denial_id}", response_class=HTMLResponse)
    def detail(
        request: Request, denial_id: int, session: SessionDep, done: str = "", outcome: str = ""
    ) -> HTMLResponse:
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
                "active": "queue",
                "back": _queue_url(request),
                "flash": flash_message(done, outcome, next_item=True),
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
        except AlreadyDecidedError as exc:
            raise HTTPException(409, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        session.flush()
        row = session.get(DenialRow, denial_id)
        flash = urlencode({"done": row.line_control_number if row else "", "outcome": action.value})
        next_id = session.scalar(
            select(DenialRow.id)
            .where(DenialRow.status == "pending")
            .order_by(DenialRow.denied_amount.desc(), DenialRow.id)
            .limit(1)
        )
        target = f"/denials/{next_id}?{flash}" if next_id else f"/?{flash}"
        return RedirectResponse(target, status_code=303)

    @app.get("/audit", response_class=HTMLResponse)
    def audit(request: Request, session: SessionDep) -> HTMLResponse:
        return TEMPLATES.TemplateResponse(
            request, "audit.html", {"events": recent_audit(session), "active": "audit"}
        )

    return app


def _queue_url(request: Request) -> str:
    """Back to the queue the reviewer came from, filters and sort intact, if we know it."""
    referer = urlparse(request.headers.get("referer", ""))
    same_host = referer.netloc in ("", request.url.netloc)
    return f"/?{referer.query}" if same_host and referer.path == "/" and referer.query else "/"
