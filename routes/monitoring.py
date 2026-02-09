from fastapi import APIRouter, Depends
from database.mongodb import get_mongo_db
from datetime import datetime, timedelta, timezone

router = APIRouter(prefix="/api/monitoring", tags=["monitoring"])



@router.get("/collections")
async def list_collections(db = Depends(get_mongo_db)):
    """List all MongoDB collections"""
    collections = await db.list_collection_names()
    return {"collections": collections}



@router.get("/runs")
async def get_runs(hours: float = 24, limit: int = 100, db = Depends(get_mongo_db)):
    """Get runs from last N hours"""
    try:
        cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
        
        cursor = db["runs"].find(
            {"run_started_at": {"$gte": cutoff}}
        ).sort("run_started_at", -1).limit(limit)
        
        runs = await cursor.to_list(length=limit)
        
        # Convert non-serializable types
        for run in runs:
            run['_id'] = str(run['_id'])
            if 'run_started_at' in run and hasattr(run['run_started_at'], 'isoformat'):
                run['run_started_at'] = run['run_started_at'].isoformat()
            if 'started_at' in run and hasattr(run['started_at'], 'isoformat'):
                run['started_at'] = run['started_at'].isoformat()
            if 'finished_at' in run and hasattr(run['finished_at'], 'isoformat'):
                run['finished_at'] = run['finished_at'].isoformat()
        
        return {"hours": hours, "count": len(runs), "runs": runs}
    except Exception as e:
        return {"error": str(e), "hours": hours, "count": 0, "runs": []}
