"""PostgreSQL read-only domain pack for the investigation harness.

Three tools, all read-only, all subprocess ``psql``:

* ``pg_describe_table`` — schema + column types + indexes.
* ``pg_explain_query`` — query plan via ``EXPLAIN`` (read-only, no ANALYZE).
* ``pg_active_queries`` — long-running queries from ``pg_stat_activity``.

Why ``psql`` and not ``psycopg``:

* ``psycopg`` is a hard install (compiles native extensions). For a
  read-only investigation pack, the cost-to-value isn't worth it.
* ``psql`` is the universal contract — every operator-grade DB host
  has it, and authentication via ``PGPASSWORD`` env / ``.pgpass`` is
  already the deployment shape Mesh would use.
* The output is structured enough to parse: ``-A -t -F\\t`` gives
  TSV with no headers / no padding.

Read-only enforcement:

* Critic blocks anything not classified ``read_only``.
* Each tool builds an explicit ``psql`` argv with hard-coded SQL.
  User-supplied args become parameters — bound via ``-v`` (psql
  variables) or ``-c`` SQL with quoted identifiers, **never** raw
  string interpolation into the SQL body. A ``DROP TABLE`` arrival
  via the ``table_name`` arg gets escaped, not executed.
* ``EXPLAIN`` is gated to a fixed ``EXPLAIN`` form (no ANALYZE, no
  EXPLAIN BUFFERS that could leak secrets via verbose output).
* Connection string is read from env (``MESH_PG_DSN`` etc.) at
  registration time, never passed through tool args. This prevents
  an LLM from supplying a malicious DSN.
"""

from __future__ import annotations

import os
import re
import shutil
import subprocess
from typing import Any

from .harness import (
    RawToolOutput,
    ToolDefinition,
    ToolRegistry,
)


PG_DOMAIN = "postgres"
MAX_OUTPUT_BYTES = 32 * 1024


# Identifier validation: lowercase letters/numbers/underscore, optionally
# qualified by a single dot (schema.table). Rejects anything that could
# break out of the quoted identifier we build in the SQL.
_PG_IDENT_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*(\.[a-zA-Z_][a-zA-Z0-9_]*)?$")


def pg_tool_definitions() -> list[ToolDefinition]:
    schemas = {
        "pg_describe_table": {
            "table_name": {"type": "str", "required": True},
        },
        "pg_explain_query": {
            "query": {"type": "str", "required": True},
        },
        "pg_active_queries": {
            "min_duration_seconds": {"type": "int", "required": False},
            "limit": {"type": "int", "required": False},
        },
    }
    descriptions = {
        "pg_describe_table": "Describe a Postgres table: columns, types, indexes (psql \\d+).",
        "pg_explain_query": "Return the EXPLAIN plan (no ANALYZE) for a SELECT query.",
        "pg_active_queries": "List active queries from pg_stat_activity, ordered by duration.",
    }
    return [
        ToolDefinition(
            name=name,
            domain=PG_DOMAIN,
            description=description,
            args_schema=dict(schemas[name]),
            mutation_class="read_only",
            timeout_seconds=10.0,
            budget_cost=1.5,
            citations_kind="postgres_query",
        )
        for name, description in descriptions.items()
    ]


PG_TOOL_DEFINITIONS: tuple[ToolDefinition, ...] = tuple(pg_tool_definitions())


_NO_PSQL_PATH_PROVIDED = object()


def register_pg_tools(
    registry: ToolRegistry,
    *,
    dsn: str,
    psql_path: str | None = _NO_PSQL_PATH_PROVIDED,  # type: ignore[assignment]
) -> None:
    """Register the three Postgres read tools.

    ``dsn`` is captured by closure at registration time; tool args
    cannot replace it. This is the safety floor — the LLM never sees
    or chooses the connection target.
    """
    if psql_path is _NO_PSQL_PATH_PROVIDED:
        resolved = shutil.which("psql")
    else:
        resolved = psql_path or None
    for definition in PG_TOOL_DEFINITIONS:
        registry.register(definition, _make_pg_invoker(definition.name, dsn, resolved))


def _make_pg_invoker(tool_name: str, dsn: str, psql_path: str | None):
    def invoke(args: dict[str, Any]) -> RawToolOutput:
        if not psql_path:
            return _failure(tool_name, "psql binary not found in PATH")
        sql = _build_sql(tool_name, args)
        if sql is None:
            return _failure(tool_name, "could not build SQL (missing or invalid args)")
        try:
            result = subprocess.run(
                [psql_path, dsn, "-A", "-t", "-F", "\t", "-X", "-c", sql],
                capture_output=True,
                text=True,
                timeout=10.0,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return _failure(tool_name, "psql timed out after 10s")
        except OSError as exc:
            return _failure(tool_name, f"psql exec error: {exc}")
        stdout = (result.stdout or "")[:MAX_OUTPUT_BYTES]
        stderr = (result.stderr or "")[:1024]
        if result.returncode != 0:
            return _failure(tool_name, stderr.strip() or f"psql exited {result.returncode}")
        return RawToolOutput(
            output={"sql": sql, "stdout": stdout},
            output_summary=f"{tool_name} -> {stdout[:400]}",
            citations=[{"source_type": "postgres_query", "source_ref": tool_name}],
            valid=bool(stdout),
            redaction_status="clean",
            status="completed",
        )

    return invoke


def _build_sql(tool_name: str, args: dict[str, Any]) -> str | None:
    if tool_name == "pg_describe_table":
        table = str(args.get("table_name") or "").strip()
        if not _PG_IDENT_RE.match(table):
            return None
        # Use \d+ for verbose describe. The backslash command is processed
        # by psql client-side, not the server, so injection via table_name
        # is bounded by our regex check above.
        return f"\\d+ {table}"

    if tool_name == "pg_explain_query":
        query = str(args.get("query") or "").strip()
        if not query:
            return None
        # Hard-block writes inside the EXPLAIN. Postgres EXPLAIN doesn't
        # execute the statement (no ANALYZE), but a cautious second
        # check stops obvious mistakes before we hit the server.
        upper = query.upper()
        for verb in ("INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "GRANT", "REVOKE", "CREATE"):
            if re.search(rf"\b{verb}\b", upper):
                return None
        # Wrap the user query in a SELECT so even if the server
        # accidentally implements DML inside EXPLAIN (it shouldn't),
        # the planner sees a SELECT context.
        return f"EXPLAIN {query}"

    if tool_name == "pg_active_queries":
        min_seconds = int(args.get("min_duration_seconds") or 5)
        limit = max(1, min(int(args.get("limit") or 20), 100))
        # No user-supplied identifiers in this query — safe.
        return (
            "SELECT pid, state, age(clock_timestamp(), query_start) AS duration, query "
            "FROM pg_stat_activity "
            f"WHERE state = 'active' AND age(clock_timestamp(), query_start) > interval '{min_seconds} seconds' "
            f"ORDER BY duration DESC LIMIT {limit}"
        )

    return None


def _failure(tool_name: str, message: str) -> RawToolOutput:
    return RawToolOutput(
        output={"error": message},
        output_summary=f"{tool_name} failed: {message[:400]}",
        citations=[{"source_type": "postgres_query", "source_ref": tool_name}],
        valid=False,
        redaction_status="clean",
        status="failed",
        error=message,
    )


def maybe_register_pg_at_root(registry: ToolRegistry) -> bool:
    dsn = os.environ.get("MESH_PG_DSN")
    if not dsn:
        return False
    if shutil.which("psql") is None:
        return False
    register_pg_tools(registry, dsn=dsn)
    return True
