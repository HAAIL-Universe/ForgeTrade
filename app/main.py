"""ForgeTrade — application entry point.

Boots the FastAPI internal server with health, status, and trades endpoints.
"""

from fastapi import FastAPI

from app.api.routers import router

app = FastAPI(title="ForgeTrade Internal API", version="0.1.0")
app.include_router(router)


@app.get("/health")
async def health():
    """Health check required by Forge verification gates."""
    return {"status": "ok"}
