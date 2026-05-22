import argparse
import csv
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Optional

ROOT_DIR = Path(__file__).resolve().parent
LOGS_DIR = ROOT_DIR / "logs"
SPIDER_NAME = "Nizami_Google_Scraper"
MAX_QUERIES = 10
MAX_EMPTY_RETRIES = 5


@dataclass
class WorkerRun:
    worker_name: str
    worker_dir: Path
    query: str
    log_path: Path
    csv_before: set[str]
    status: str = "queued"
    started_at: float = 0.0
    finished_at: float = 0.0
    rows_scraped: Optional[int] = None
    csv_path: Optional[Path] = None
    problem: str = ""
    attempt_number: int = 0
    log_paths: list[Path] = field(default_factory=list)
    process: Optional[subprocess.Popen] = field(default=None, repr=False)
    return_code: Optional[int] = None

    @property
    def elapsed_seconds(self) -> float:
        if not self.started_at:
            return 0.0
        if self.finished_at:
            return max(0.0, self.finished_at - self.started_at)
        return max(0.0, time.time() - self.started_at)

    @property
    def total_allowed_attempts(self) -> int:
        return 1 + MAX_EMPTY_RETRIES

    @property
    def attempts_label(self) -> str:
        current = self.attempt_number if self.attempt_number else 1
        return f"{current}/{self.total_allowed_attempts}"


def discover_workers() -> list[Path]:
    workers = []
    for path in ROOT_DIR.glob("Worker_*"):
        if path.is_dir() and (path / "scrapy.cfg").exists():
            workers.append(path)
    return sorted(workers, key=worker_sort_key)


def worker_sort_key(path: Path) -> tuple[int, str]:
    suffix = path.name.split("_")[-1]
    try:
        return int(suffix), path.name
    except ValueError:
        return 10**9, path.name


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run one Google Maps query per worker and track live status."
    )
    parser.add_argument(
        "--query",
        action="append",
        dest="queries",
        help="Search query to assign to a worker. Repeat this flag for multiple queries.",
    )
    parser.add_argument(
        "--refresh-seconds",
        type=float,
        default=1.0,
        help="How often to refresh the live status table.",
    )
    return parser.parse_args()


def collect_queries(worker_count: int, cli_queries: Optional[list[str]]) -> list[str]:
    max_queries = min(MAX_QUERIES, worker_count)
    queries = [query.strip() for query in (cli_queries or []) if query and query.strip()]

    if queries:
        if len(queries) > max_queries:
            print(
                f"Received {len(queries)} queries but only {max_queries} workers are available. "
                f"Using the first {max_queries} queries."
            )
            return queries[:max_queries]
        return queries

    print(f"Found {worker_count} workers. You can assign up to {max_queries} queries.")
    while True:
        raw_count = input(f"How many queries do you want to run? [1-{max_queries}]: ").strip()
        try:
            query_count = int(raw_count)
        except ValueError:
            print("Please enter a number.")
            continue

        if 1 <= query_count <= max_queries:
            break

        print(f"Please enter a value between 1 and {max_queries}.")

    queries = []
    for index in range(1, query_count + 1):
        while True:
            query = input(f"Enter query {index}: ").strip()
            if query:
                queries.append(query)
                break
            print("Query cannot be empty.")
    return queries


def get_worker_python() -> Path:
    venv_python = ROOT_DIR / ".venv" / "Scripts" / "python.exe"
    if venv_python.exists():
        return venv_python
    return Path(sys.executable)


def build_log_path(run_logs_dir: Path, worker_name: str, attempt_number: int) -> Path:
    return run_logs_dir / f"{worker_name}_attempt_{attempt_number}.log"


def launch_worker(run: WorkerRun, python_exe: Path, run_logs_dir: Path) -> None:
    run.attempt_number += 1
    run.csv_before = {path.name for path in run.worker_dir.glob("*.csv")}
    run.log_path = build_log_path(run_logs_dir, run.worker_name, run.attempt_number)
    run.log_paths.append(run.log_path)
    run.csv_path = None
    run.rows_scraped = None
    run.return_code = None
    run.process = None
    run.finished_at = 0.0
    run.started_at = 0.0

    if run.attempt_number == 1:
        run.status = "starting"
        run.problem = ""
    else:
        run.status = "retrying"
        run.problem = (
            f"Retrying empty result: attempt {run.attempt_number}/{run.total_allowed_attempts}"
        )

    log_handle = open(run.log_path, "w", encoding="utf-8")
    command = [
        str(python_exe),
        "-m",
        "scrapy",
        "crawl",
        SPIDER_NAME,
        "-a",
        f"search={run.query}",
        "-L",
        "INFO",
    ]

    try:
        run.process = subprocess.Popen(
            command,
            cwd=run.worker_dir,
            stdout=log_handle,
            stderr=subprocess.STDOUT,
            text=True,
        )
        log_handle.close()
        run.started_at = time.time()
        run.status = "running" if run.attempt_number == 1 else "retrying"
    except Exception as exc:
        log_handle.close()
        run.status = "spawn_failed"
        run.problem = str(exc)
        run.finished_at = time.time()


def start_worker_runs(workers: list[Path], queries: list[str], run_logs_dir: Path) -> list[WorkerRun]:
    python_exe = get_worker_python()
    worker_runs: list[WorkerRun] = []

    for worker_dir, query in zip(workers, queries):
        worker_name = worker_dir.name
        run = WorkerRun(
            worker_name=worker_name,
            worker_dir=worker_dir,
            query=query,
            log_path=build_log_path(run_logs_dir, worker_name, 1),
            csv_before=set(),
        )
        worker_runs.append(run)
        launch_worker(run, python_exe, run_logs_dir)

    return worker_runs


def find_new_csv(worker_dir: Path, existing_names: set[str], started_at: float) -> Optional[Path]:
    new_files = [path for path in worker_dir.glob("*.csv") if path.name not in existing_names]
    if new_files:
        return max(new_files, key=lambda path: path.stat().st_mtime)

    updated_files = [
        path for path in worker_dir.glob("*.csv") if path.stat().st_mtime >= max(0.0, started_at - 1)
    ]
    if updated_files:
        return max(updated_files, key=lambda path: path.stat().st_mtime)
    return None


def count_scraped_rows(csv_path: Path) -> int:
    with open(csv_path, "r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        rows = 0
        for row in reader:
            if any((value or "").strip() for value in row.values()):
                rows += 1
        return rows


def tail_log(log_path: Path, line_count: int = 6) -> str:
    if not log_path.exists():
        return "log file missing"

    lines = log_path.read_text(encoding="utf-8", errors="replace").splitlines()
    interesting = [line.strip() for line in lines if line.strip()]
    if not interesting:
        return "no log output"

    for line in reversed(interesting):
        if "Traceback" in line or " ERROR:" in line or "[ERROR]" in line or "ModuleNotFoundError" in line:
            return line[-140:]

    return " | ".join(interesting[-line_count:])[-200:]


def finalize_run(run: WorkerRun) -> None:
    run.finished_at = time.time()

    if run.status == "spawn_failed":
        return

    if run.process is None:
        run.status = "failed"
        run.problem = "process was not created"
        return

    run.return_code = run.process.poll()
    csv_path = find_new_csv(run.worker_dir, run.csv_before, run.started_at)
    run.csv_path = csv_path

    if csv_path is None:
        run.rows_scraped = 0
        run.problem = "Worker finished but no CSV was created"
        run.status = "no_csv" if run.return_code == 0 else "failed"
        if run.return_code != 0:
            run.problem = tail_log(run.log_path)
        return

    run.rows_scraped = count_scraped_rows(csv_path)

    if run.return_code != 0:
        run.status = "failed"
        run.problem = tail_log(run.log_path)
    elif run.rows_scraped == 0:
        run.status = "csv_empty"
        run.problem = "CSV created but no scraped rows were found"
    else:
        run.status = "completed"
        run.problem = ""


def maybe_retry_empty_run(run: WorkerRun, python_exe: Path, run_logs_dir: Path) -> None:
    if run.status not in {"csv_empty", "no_csv"}:
        return

    if run.attempt_number >= run.total_allowed_attempts:
        if run.status == "csv_empty":
            run.problem = (
                f"CSV stayed empty after {run.total_allowed_attempts} attempts"
            )
        else:
            run.problem = (
                f"No CSV was created after {run.total_allowed_attempts} attempts"
            )
        return

    launch_worker(run, python_exe, run_logs_dir)


def update_running_workers(worker_runs: list[WorkerRun], python_exe: Path, run_logs_dir: Path) -> None:
    for run in worker_runs:
        if run.status not in {"running", "starting", "retrying"}:
            continue

        if run.process is None:
            run.status = "failed"
            run.finished_at = time.time()
            run.problem = "process missing"
            continue

        return_code = run.process.poll()
        if return_code is None:
            run.status = "running"
            continue

        run.return_code = return_code
        finalize_run(run)
        maybe_retry_empty_run(run, python_exe, run_logs_dir)


def status_style(status: str) -> str:
    styles = {
        "queued": "white",
        "starting": "yellow",
        "running": "cyan",
        "retrying": "bright_blue",
        "completed": "green",
        "csv_empty": "yellow",
        "no_csv": "magenta",
        "failed": "bold red",
        "spawn_failed": "bold red",
    }
    return styles.get(status, "white")


def build_table(worker_runs: list[WorkerRun], run_logs_dir: Path):
    from rich.table import Table

    table = Table(title=f"Nizami Worker Manager | Logs: {run_logs_dir}", expand=True)
    table.add_column("Worker", style="bold")
    table.add_column("Status")
    table.add_column("Attempt", justify="right")
    table.add_column("Rows", justify="right")
    table.add_column("Elapsed", justify="right")
    table.add_column("Query", overflow="fold")
    table.add_column("CSV", overflow="fold")
    table.add_column("Log", overflow="fold")
    table.add_column("Problem", overflow="fold")

    for run in worker_runs:
        rows = "-" if run.rows_scraped is None else str(run.rows_scraped)
        csv_name = run.csv_path.name if run.csv_path else "-"
        table.add_row(
            run.worker_name,
            f"[{status_style(run.status)}]{run.status}[/{status_style(run.status)}]",
            run.attempts_label,
            rows,
            f"{run.elapsed_seconds:.0f}s",
            run.query,
            csv_name,
            run.log_path.name,
            run.problem or "-",
        )
    return table


def print_final_summary(console, worker_runs: list[WorkerRun], run_logs_dir: Path) -> None:
    completed = sum(1 for run in worker_runs if run.status == "completed")
    failed = sum(1 for run in worker_runs if run.status in {"failed", "spawn_failed"})
    no_csv = sum(1 for run in worker_runs if run.status == "no_csv")
    csv_empty = sum(1 for run in worker_runs if run.status == "csv_empty")
    total_rows = sum(run.rows_scraped or 0 for run in worker_runs)

    console.print()
    console.print(f"Run finished. Logs saved in: {run_logs_dir}")
    console.print(
        f"Completed: {completed} | Failed: {failed} | No CSV: {no_csv} | "
        f"CSV Empty: {csv_empty} | Total Rows: {total_rows}"
    )

    for run in worker_runs:
        console.print(
            f"{run.worker_name}: {run.status} | attempts={run.attempt_number}/{run.total_allowed_attempts} "
            f"| rows={run.rows_scraped or 0} | csv={run.csv_path.name if run.csv_path else '-'} "
            f"| log={run.log_path.name}"
        )


def ensure_rich_installed() -> None:
    try:
        import rich  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "The 'rich' package is not installed. Install requirements first with "
            "'.\\.venv\\Scripts\\python.exe -m pip install -r Requirements.txt'."
        ) from exc


def main() -> int:
    ensure_rich_installed()
    from rich.console import Console
    from rich.live import Live

    args = parse_args()
    console = Console()

    workers = discover_workers()
    if not workers:
        console.print("No worker folders with scrapy.cfg were found.", style="bold red")
        return 1

    queries = collect_queries(len(workers), args.queries)
    if not queries:
        console.print("No queries were provided.", style="bold red")
        return 1

    LOGS_DIR.mkdir(exist_ok=True)
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    run_logs_dir = LOGS_DIR / timestamp
    run_logs_dir.mkdir(exist_ok=True)
    python_exe = get_worker_python()

    worker_runs = start_worker_runs(workers, queries, run_logs_dir)
    idle_workers = workers[len(queries):]

    if idle_workers:
        idle_names = ", ".join(worker.name for worker in idle_workers)
        console.print(f"Idle workers this run: {idle_names}", style="yellow")

    with Live(build_table(worker_runs, run_logs_dir), console=console, refresh_per_second=4) as live:
        while True:
            update_running_workers(worker_runs, python_exe, run_logs_dir)
            live.update(build_table(worker_runs, run_logs_dir))
            if all(run.status not in {"queued", "starting", "running", "retrying"} for run in worker_runs):
                break
            time.sleep(max(0.2, args.refresh_seconds))

    print_final_summary(console, worker_runs, run_logs_dir)
    return 0 if all(run.status == "completed" for run in worker_runs) else 1


if __name__ == "__main__":
    raise SystemExit(main())
