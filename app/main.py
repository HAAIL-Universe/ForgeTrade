"""ForgeTrade — application entry point.

Boots the FastAPI internal server with a /health endpoint.
"""

from fastapi import FastAPI

app = FastAPI(title="ForgeTrade Internal API", version="0.1.0")


@app.get("/health")
async def health():
    """Health check required by Forge verification gates."""
    return {"status": "ok"}
