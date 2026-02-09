import os
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
import uvicorn

from routes.communes import router as communes_router
from routes.agencies import router as agencies_router
from routes.provisioning import router as provisioning_router
from routes.monitoring import router as monitoring_router

app = FastAPI(
    title="Neuraplex API",
    description="Real estate analytics platform API",
    version="1.0.0"
)

# API Key protection
API_KEY = os.getenv("API_KEY")
UNPROTECTED_PATHS = {"/", "/health", "/docs", "/openapi.json", "/redoc"}

@app.middleware("http")
async def verify_api_key(request: Request, call_next):
    if API_KEY and request.url.path not in UNPROTECTED_PATHS:
        if request.headers.get("X-API-Key") != API_KEY:
            return JSONResponse(status_code=401, content={"error": "unauthorized"})
    return await call_next(request)

# CORS Middleware (restrict later when you have domain)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # TODO: restrict to your frontend domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Include routers
app.include_router(communes_router)
app.include_router(agencies_router)
app.include_router(provisioning_router)
app.include_router(monitoring_router)


@app.get("/")
async def root():
    return {"message": "Neuraplex API", "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
