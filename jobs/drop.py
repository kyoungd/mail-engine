"""The drop job: pick up approved waves whose scheduled date has arrived and execute
each through the print seam. execute_wave does the idempotency and drift-halt; this
just selects what is due."""

from datetime import date

from db.readonly import readonly_connection
from domain.types import ExecutionReport
from seams.print_api import PrintApi
from service.execution import execute_wave


def run_drops(print_api: PrintApi, as_of: date) -> list[ExecutionReport]:
    with readonly_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "select id from waves "
                "where status = 'approved' and scheduled_for <= %s "
                "order by scheduled_for, created_at",
                (as_of,),
            )
            due = [r[0] for r in cur.fetchall()]
    return [execute_wave(wave_id, print_api) for wave_id in due]
