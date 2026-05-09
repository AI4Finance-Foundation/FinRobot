"""Interactive export endpoints.

POST /api/export/excel/dcf — generates .xlsx from client-provided DCFInputs+DCFResult.
This reflects the user's current interactive assumptions, not the pipeline cache.
"""

from __future__ import annotations

import io

from fastapi import APIRouter
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from finagent.engine.compute.spreadsheet_gen import generate_dcf_excel
from finagent.engine.models.financial import DCFInputs, DCFResult

router = APIRouter(prefix="/api/export", tags=["export"])


class DcfExportRequest(BaseModel):
    ticker: str
    inputs: DCFInputs
    result: DCFResult


@router.post("/excel/dcf")
async def export_dcf_excel_interactive(req: DcfExportRequest) -> StreamingResponse:
    """Generate DCF Excel from client-provided inputs/result (interactive mode)."""
    xlsx_bytes = generate_dcf_excel(req.result, req.inputs)
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={
            "Content-Disposition": f"attachment; filename={req.ticker.upper()}_dcf.xlsx"
        },
    )
