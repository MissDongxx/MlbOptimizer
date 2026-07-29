from concurrent.futures import ProcessPoolExecutor

import asyncio
from fastapi import APIRouter
from fastapi.responses import JSONResponse

from models.schemas import OptimizeRequest, OptimizeResponse
from services.optimizer import OptimizerError, run_optimizer_sync

router = APIRouter()
executor = ProcessPoolExecutor(max_workers=2)


@router.post("/", response_model=OptimizeResponse)
async def run_optimizer(request: OptimizeRequest) -> OptimizeResponse | JSONResponse:
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(executor, run_optimizer_sync, request)
    except OptimizerError as exc:
        # `detail` remains a string for existing clients; `error` adds a backward-compatible
        # structured machine-readable reason.
        return JSONResponse(
            status_code=400,
            content={"detail": str(exc), "error": exc.to_dict()},
        )


def shutdown_optimizer_executor() -> None:
    executor.shutdown(wait=False, cancel_futures=True)
