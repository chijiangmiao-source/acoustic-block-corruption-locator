"""FastAPI application: synchronous upload-and-inspect endpoint for ACLG records."""

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import JSONResponse

from .parser import RecordError, parse_record
from .schemas import ErrorBody, FailResponse, PassResponse

MAX_UPLOAD_BYTES = 8 * 1024 * 1024  # 8 MiB

app = FastAPI(
    title="ACLG Acoustic Record Inspector",
    version="1.0.0",
    description="Validates acoustic-inspection binary records and reports the first structural error.",
)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@app.post(
    "/inspect",
    response_model=PassResponse,
    responses={
        413: {"description": "Upload exceeds the 8 MiB limit"},
        422: {"model": FailResponse, "description": "Record failed structural validation"},
    },
)
async def inspect(file: UploadFile = File(...)) -> PassResponse | JSONResponse:
    # Read at most one byte past the limit so oversize uploads are rejected
    # without buffering the whole body.
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(
            status_code=413,
            detail=f"upload exceeds the 8 MiB limit ({MAX_UPLOAD_BYTES} bytes)",
        )

    try:
        summary = parse_record(data)
    except RecordError as exc:
        body = FailResponse(
            error=ErrorBody(code=exc.code, message=exc.message, block_index=exc.block_index)
        )
        return JSONResponse(status_code=422, content=body.model_dump(mode="json"))

    return PassResponse(
        block_count=summary.block_count,
        total_samples=summary.total_samples,
    )
