from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from routes.communes import router as communes_router
from routes.agencies import router as agencies_router

app = FastAPI(
    title="Neuraplex API",
    description="Real estate analytics platform API",
    version="1.0.0"
)

# CORS Middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Include routers
app.include_router(communes_router)
app.include_router(agencies_router)


@app.get("/")
async def root():
    return {"message": "Neuraplex API", "docs": "/docs"}


@app.get("/health")
async def health():
    return {"status": "ok"}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
