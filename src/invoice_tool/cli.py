"""Command line: invoice-tool process <input_dir> --out <file.xlsx> [--watch] [--replay DIR]"""

from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Annotated

import typer
from dotenv import find_dotenv, load_dotenv

from invoice_tool.cache import ExtractionCache
from invoice_tool.config import load_settings
from invoice_tool.excel import write_workbook
from invoice_tool.extractor import PROMPT_VERSION, ExtractionError, GeminiExtractor
from invoice_tool.pipeline import RunResult, run, write_json

app = typer.Typer(add_completion=False, no_args_is_help=True, help=__doc__)

EXIT_QUOTA = 3


@app.callback()
def main() -> None:
    """Extract, validate and summarise GST invoices and receipts into an Excel workbook."""


def _report(result: RunResult, out: Path) -> None:
    status = Counter(
        "Failed" if r.extracted is None else "Review" if r.flags else "OK" for r in result.records
    )
    codes = Counter(code for r in result.records for code in r.flag_codes)
    typer.echo(
        f"\n{len(result.records)} documents -> {out}  "
        f"(OK {status['OK']}, needs review {status['Review']}, failed {status['Failed']})"
    )
    typer.echo(f"API calls: {result.live_calls}, cached: {result.cache_hits}")
    for code, n in sorted(codes.items()):
        typer.echo(f"  {code:<28}{n}")
    if result.pending:
        typer.echo(
            f"\nDaily Gemini quota reached: {len(result.pending)} file(s) not processed yet. "
            "Re-run the same command after the quota resets (midnight Pacific time); "
            "finished files are cached and will not be re-sent."
        )


@app.command()
def process(
    input_dir: Annotated[
        Path, typer.Argument(exists=True, file_okay=False, help="Folder of PDFs/JPGs/PNGs")
    ],
    out: Annotated[Path, typer.Option("--out", "-o", help="Excel file to write")],
    watch: Annotated[
        bool, typer.Option("--watch", help="Keep running; reprocess when files arrive")
    ] = False,
    replay: Annotated[
        Path | None,
        typer.Option("--replay", help="Use recorded responses from this folder; no API key needed"),
    ] = None,
    json_out: Annotated[
        Path | None, typer.Option("--json-out", help="Also write results as JSON")
    ] = None,
    config_dir: Annotated[
        Path | None, typer.Option("--config-dir", help="Folder with settings.toml")
    ] = None,
    model: Annotated[
        str | None, typer.Option("--model", help="Override the configured Gemini model")
    ] = None,
) -> None:
    """Process every PDF / JPG / PNG in INPUT_DIR and write the review workbook."""
    load_dotenv(find_dotenv(usecwd=True))  # .env from the working directory only
    settings = load_settings(config_dir, model=model)
    if replay:
        cache = ExtractionCache(replay, PROMPT_VERSION, read_only=True)
        extractor = None
    else:
        cache = ExtractionCache(settings.cache_dir, PROMPT_VERSION)
        try:
            extractor = GeminiExtractor(
                settings.model,
                settings.categories,
                max_retries=settings.max_retries,
                initial_backoff=settings.initial_backoff_seconds,
                max_backoff=settings.max_backoff_seconds,
                timeout_seconds=settings.request_timeout_seconds,
                on_retry=typer.echo,
            )
        except ExtractionError as exc:
            typer.echo(f"Error: {exc}", err=True)
            raise typer.Exit(code=2) from exc

    def once() -> RunResult:
        result = run(input_dir, settings, cache, extractor, replay=bool(replay), log=typer.echo)
        write_workbook(result.records, out)
        if json_out:
            write_json(result, json_out, input_dir)
        _report(result, out)
        return result

    if watch:
        from invoice_tool.watch import watch as watch_folder

        typer.echo(f"Watching {input_dir} (Ctrl+C to stop)")
        try:
            watch_folder(input_dir, once)
        except KeyboardInterrupt:
            typer.echo("Stopped.")
        return

    result = once()
    if result.quota_reached:
        raise typer.Exit(code=EXIT_QUOTA)
