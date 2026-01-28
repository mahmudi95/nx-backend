from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import List, Optional

from database.connection import get_db

router = APIRouter(prefix="/api/agencies", tags=["agencies"])

# Property type view mapping
PROPERTY_VIEWS = {
    "apartment": "mv_apartment_clean_daily",
    "house": "mv_house_clean_daily",
}

def get_view(property_type: str) -> str:
    """Get the materialized view name for a property type"""
    return PROPERTY_VIEWS.get(property_type, PROPERTY_VIEWS["apartment"])


@router.get("")
async def get_agencies_leaderboard(
    type: str = Query("apartment", description="Property type: apartment, house"),
    db: AsyncSession = Depends(get_db)
):
    """Get full agency leaderboard with listing counts"""
    try:
        view = get_view(type)
        result = await db.execute(text(f"""
            SELECT 
                agency_name,
                COUNT(DISTINCT listing_fingerprint) as listings,
                COUNT(DISTINCT commune_clean) as communes_covered,
                ROUND(AVG(price)::numeric, 0) as avg_price
            FROM {view}
            WHERE status = 'active' AND agency_name IS NOT NULL AND agency_name != ''
            GROUP BY agency_name
            ORDER BY listings DESC
        """))
        agencies = [dict(row._mapping) for row in result.fetchall()]
        
        total_listings = sum(a['listings'] for a in agencies)
        
        return {
            "agencies": agencies,
            "total_agencies": len(agencies),
            "total_listings": total_listings
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/trends")
async def get_agencies_trends(
    type: str = Query("apartment", description="Property type: apartment, house"),
    db: AsyncSession = Depends(get_db)
):
    """Get agencies gaining/losing listings (30d vs previous 30d)"""
    try:
        view = get_view(type)
        result = await db.execute(text(f"""
            WITH recent AS (
                SELECT agency_name, COUNT(DISTINCT listing_fingerprint) as count
                FROM {view}
                WHERE created_at >= NOW() - INTERVAL '30 days'
                  AND agency_name IS NOT NULL AND agency_name != ''
                GROUP BY agency_name
            ),
            previous AS (
                SELECT agency_name, COUNT(DISTINCT listing_fingerprint) as count
                FROM {view}
                WHERE created_at >= NOW() - INTERVAL '60 days'
                  AND created_at < NOW() - INTERVAL '30 days'
                  AND agency_name IS NOT NULL AND agency_name != ''
                GROUP BY agency_name
            )
            SELECT 
                COALESCE(r.agency_name, p.agency_name) as agency_name,
                COALESCE(r.count, 0) as recent,
                COALESCE(p.count, 0) as previous,
                COALESCE(r.count, 0) - COALESCE(p.count, 0) as change
            FROM recent r
            FULL OUTER JOIN previous p ON r.agency_name = p.agency_name
            ORDER BY change DESC
        """))
        trends = [dict(row._mapping) for row in result.fetchall()]
        return {"trends": trends}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/compare")
async def compare_agencies(
    agencies: str = Query(..., description="Comma-separated agency names"),
    type: str = Query("apartment", description="Property type: apartment, house"),
    db: AsyncSession = Depends(get_db)
):
    """Compare multiple agencies side-by-side"""
    try:
        view = get_view(type)
        agency_list = [a.strip() for a in agencies.split(",") if a.strip()]
        if not agency_list or len(agency_list) > 5:
            raise HTTPException(status_code=400, detail="Provide 1-5 agencies")
        
        results = []
        for agency in agency_list:
            # Get agency stats
            stats_result = await db.execute(text(f"""
                SELECT 
                    agency_name,
                    COUNT(DISTINCT listing_fingerprint) as listings,
                    COUNT(DISTINCT commune_clean) as communes_covered,
                    ROUND(AVG(price)::numeric, 0) as avg_price,
                    ROUND(AVG(price_per_sqm)::numeric, 0) as avg_price_per_sqm
                FROM {view}
                WHERE agency_name = :agency AND status = 'active'
                GROUP BY agency_name
            """), {"agency": agency})
            stats_row = stats_result.fetchone()
            
            if not stats_row:
                continue
                
            stats = dict(stats_row._mapping)
            
            # Get top communes for this agency
            communes_result = await db.execute(text(f"""
                SELECT commune_clean as commune, COUNT(DISTINCT listing_fingerprint) as count
                FROM {view}
                WHERE agency_name = :agency AND status = 'active'
                GROUP BY commune_clean
                ORDER BY count DESC
                LIMIT 5
            """), {"agency": agency})
            stats["top_communes"] = [dict(row._mapping) for row in communes_result.fetchall()]
            
            results.append(stats)
        
        return {"comparison": results}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/{agency}/communes")
async def get_agency_communes(
    agency: str,
    type: str = Query("apartment", description="Property type: apartment, house"),
    db: AsyncSession = Depends(get_db)
):
    """Get market share by commune for a specific agency"""
    try:
        view = get_view(type)
        result = await db.execute(text(f"""
            SELECT commune_clean as commune, COUNT(DISTINCT listing_fingerprint) as count
            FROM {view}
            WHERE agency_name = :agency AND status = 'active'
            GROUP BY commune_clean
            ORDER BY count DESC
            LIMIT 10
        """), {"agency": agency})
        communes = [dict(row._mapping) for row in result.fetchall()]
        
        if not communes:
            raise HTTPException(status_code=404, detail=f"Agency '{agency}' not found")
        
        return {"agency": agency, "communes": communes}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
