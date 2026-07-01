from concurrent.futures import ProcessPoolExecutor

import asyncio
from fastapi import APIRouter, HTTPException

from models.schemas import OptimizeRequest, OptimizeResponse
from services.optimizer import OptimizerError, run_optimizer_sync

router = APIRouter()
executor = ProcessPoolExecutor(max_workers=2)


@router.post("/", response_model=OptimizeResponse)
async def run_optimizer(request: OptimizeRequest) -> OptimizeResponse:
    loop = asyncio.get_running_loop()
    try:
        return await loop.run_in_executor(executor, run_optimizer_sync, request)
    except OptimizerError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


def shutdown_optimizer_executor() -> None:
    executor.shutdown(wait=False, cancel_futures=True)
