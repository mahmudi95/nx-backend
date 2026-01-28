from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text

from database.connection import get_db, test_connection

router = APIRouter(prefix="/api/communes", tags=["communes"])


@router.get("/health")
async def health_check():
    result = await test_connection()
    return result


@router.get("/overview")
async def get_communes_overview(db: AsyncSession = Depends(get_db)):
    try:
        result = await db.execute(text("SELECT * FROM v_commune_stats ORDER BY commune"))
        rows = result.fetchall()
        return {"data": [dict(row._mapping) for row in rows]}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
