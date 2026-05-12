"""Interactive export endpoints.

POST /api/export/excel/dcf  — generates .xlsx from client-provided DCFInputs+DCFResult.
POST /api/export/excel/lbo  — generates .xlsx from client-provided LBOInputs+LBOResult.
POST /api/export/excel/comps — generates .xlsx from client-provided peer list.

These reflect the user's current interactive assumptions, not the pipeline cache.
"""

from __future__ import annotations

import io

from fastapi import APIRouter
from pydantic import BaseModel
from starlette.responses import StreamingResponse

from finagent.engine.compute.spreadsheet_gen import (
    generate_comps_excel,
    generate_dcf_excel,
    generate_lbo_excel,
)
from finagent.engine.models.financial import (
    CompanyFinancials,
    DCFInputs,
    DCFResult,
    LBOInputs,
    LBOResult,
)

router = APIRouter(prefix="/api/export", tags=["export"])


class DcfExportRequest(BaseModel):
    ticker: str
    inputs: DCFInputs
    result: DCFResult


class LboExportRequest(BaseModel):
    ticker: str
    inputs: LBOInputs
    result: LBOResult


class CompsExportRequest(BaseModel):
    ticker: str
    peers: list[CompanyFinancials]


def _xlsx_response(xlsx_bytes: bytes, filename: str) -> StreamingResponse:
    """Wrap raw xlsx bytes in a StreamingResponse with correct headers."""
    return StreamingResponse(
        io.BytesIO(xlsx_bytes),
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


@router.post("/excel/dcf")
async def export_dcf_excel_interactive(req: DcfExportRequest) -> StreamingResponse:
    """Generate DCF Excel from client-provided inputs/result (interactive mode)."""
    xlsx_bytes = generate_dcf_excel(req.result, req.inputs)
    return _xlsx_response(xlsx_bytes, f"{req.ticker.upper()}_dcf.xlsx")


@router.post("/excel/lbo")
async def export_lbo_excel_interactive(req: LboExportRequest) -> StreamingResponse:
    """Generate LBO Excel from client-provided inputs/result (interactive mode)."""
    xlsx_bytes = generate_lbo_excel(req.result, req.inputs)
    return _xlsx_response(xlsx_bytes, f"{req.ticker.upper()}_lbo.xlsx")


@router.post("/excel/comps")
async def export_comps_excel_interactive(req: CompsExportRequest) -> StreamingResponse:
    """Generate Comps Excel from client-provided peer list (interactive mode)."""
    xlsx_bytes = generate_comps_excel(req.peers)
    return _xlsx_response(xlsx_bytes, f"{req.ticker.upper()}_comps.xlsx")
