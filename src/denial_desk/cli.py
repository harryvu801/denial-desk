"""Typer CLI — the operational entry point.

`dd demo` is the one-command path: generate synthetic files, then ingest them.
"""

from datetime import date
from pathlib import Path

import typer

from denial_desk.config import settings

app = typer.Typer(help="Denial Desk operations.", no_args_is_help=True)


@app.command()
def generate(claims: int = 500, seed: int = 42, out: Path | None = None) -> None:
    """Generate synthetic 837P/835 files plus the ground-truth manifest."""
    from denial_desk.ingest.generator import generate as run

    out_dir = out or Path(settings.synthetic_data_dir)
    counts = run(out_dir, claims, seed)
    typer.echo(f"wrote {counts} to {out_dir}")


def _working_date(directory: Path, as_of: str | None) -> date | None:
    """Explicit --as-of wins. Synthetic data (it has a manifest) is replayed: each denial is
    triaged as of its own remittance date, so demo numbers never depend on the day you run
    it. Anything else is triaged as of today."""
    if as_of:
        return date.fromisoformat(as_of)
    if (directory / "manifest.json").exists():
        return None
    return date.today()


@app.command()
def ingest(directory: Path | None = None, as_of: str | None = None) -> None:
    """Parse, join, triage and store every 837P/835 file in a directory. Idempotent."""
    from denial_desk.ingest.pipeline import ingest_directory
    from denial_desk.persistence.store import make_engine, session_scope

    directory = directory or Path(settings.synthetic_data_dir)
    working_date = _working_date(directory, as_of)
    with session_scope(make_engine(settings.database_url)) as session:
        s = ingest_directory(session, directory, as_of=working_date)
    share = s.deterministic / s.denials_new if s.denials_new else 0.0
    typer.echo(
        f"working date: {working_date or 'each remittance date (replay)'}\n"
        f"837 files: {s.files_837}  835 files: {s.files_835}"
        f" (already ingested: {s.remittances_skipped})\n"
        f"new denials: {s.denials_new}  existing: {s.denials_existing}"
        f"  rules lane: {s.deterministic} ({share:.0%})  join issues: {len(s.issues)}"
    )


@app.command()
def demo(claims: int = 500, seed: int = 42) -> None:
    """Generate synthetic data and ingest it, ready for `make serve`."""
    generate(claims=claims, seed=seed, out=None)
    ingest(directory=None, as_of=None)


@app.command()
def resolve(claim: str) -> None:
    """Resolve a single denial and print the proposed resolution."""
    raise NotImplementedError
