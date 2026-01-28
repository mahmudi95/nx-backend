from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import text
from typing import Optional

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


@router.get("/overview/country")
async def get_country_overview(db: AsyncSession = Depends(get_db)):
    """Get country-wide real estate market overview"""
    try:
        # Country KPIs from v_commune_stats
        kpis_result = await db.execute(text("""
            SELECT 
                SUM(active_listings) as total_listings,
                ROUND(AVG(median_price_per_sqm)::numeric, 0) as avg_price_per_sqm,
                COUNT(*) as total_communes,
                ROUND(AVG(median_days_on_market)::numeric, 0) as avg_days_on_market
            FROM v_commune_stats
        """))
        kpis = dict(kpis_result.fetchone()._mapping)
        
        # Top 10 agencies nationwide
        agencies_result = await db.execute(text("""
            SELECT agency_name, COUNT(DISTINCT listing_fingerprint) as count
            FROM mv_apartment_clean_daily
            WHERE status = 'active' AND agency_name IS NOT NULL
            GROUP BY agency_name
            ORDER BY count DESC
            LIMIT 10
        """))
        agencies = [dict(row._mapping) for row in agencies_result.fetchall()]
        
        # Portal distribution
        portals_result = await db.execute(text("""
            SELECT site, COUNT(DISTINCT listing_fingerprint) as count
            FROM mv_apartment_clean_daily
            WHERE status = 'active'
            GROUP BY site
            ORDER BY count DESC
        """))
        portals = [dict(row._mapping) for row in portals_result.fetchall()]
        
        # Price tiers - top 5 expensive and bottom 5 cheapest communes
        expensive_result = await db.execute(text("""
            SELECT commune, median_price_per_sqm, active_listings
            FROM v_commune_stats
            ORDER BY median_price_per_sqm DESC
            LIMIT 5
        """))
        expensive = [dict(row._mapping) for row in expensive_result.fetchall()]
        
        cheapest_result = await db.execute(text("""
            SELECT commune, median_price_per_sqm, active_listings
            FROM v_commune_stats
            ORDER BY median_price_per_sqm ASC
            LIMIT 5
        """))
        cheapest = [dict(row._mapping) for row in cheapest_result.fetchall()]
        
        # Energy class distribution
        energy_result = await db.execute(text("""
            SELECT 
                COUNT(DISTINCT listing_fingerprint) FILTER (WHERE energy_class IN ('a', 'b', 'A', 'B')) AS energy_ab,
                COUNT(DISTINCT listing_fingerprint) FILTER (WHERE energy_class IN ('c', 'd', 'C', 'D')) AS energy_cd,
                COUNT(DISTINCT listing_fingerprint) FILTER (WHERE energy_class IN ('e', 'f', 'g', 'E', 'F', 'G')) AS energy_efg,
                COUNT(DISTINCT listing_fingerprint) FILTER (WHERE energy_class IS NULL OR energy_class = '') AS energy_unknown
            FROM mv_apartment_clean_daily
            WHERE status = 'active'
        """))
        energy = dict(energy_result.fetchone()._mapping)
        
        # Monthly inventory (new listings per month, last 12 months)
        monthly_result = await db.execute(text("""
            SELECT 
                TO_CHAR(DATE_TRUNC('month', created_at), 'YYYY-MM') as month,
                COUNT(DISTINCT listing_fingerprint) as new_listings
            FROM mv_apartment_clean_daily
            WHERE created_at >= NOW() - INTERVAL '12 months'
            GROUP BY DATE_TRUNC('month', created_at)
            ORDER BY month ASC
        """))
        monthly_inventory = [dict(row._mapping) for row in monthly_result.fetchall()]
        
        # Bedroom distribution (country-wide)
        bedrooms_result = await db.execute(text("""
            SELECT 
                COUNT(DISTINCT listing_fingerprint) FILTER (WHERE bedrooms = 1) as bed_1,
                COUNT(DISTINCT listing_fingerprint) FILTER (WHERE bedrooms = 2) as bed_2,
                COUNT(DISTINCT listing_fingerprint) FILTER (WHERE bedrooms = 3) as bed_3,
                COUNT(DISTINCT listing_fingerprint) FILTER (WHERE bedrooms >= 4) as bed_4plus
            FROM mv_apartment_clean_daily
            WHERE status = 'active'
        """))
        bedrooms = dict(bedrooms_result.fetchone()._mapping)
        
        return {
            "kpis": kpis,
            "agencies": agencies,
            "portals": portals,
            "price_tiers": {"expensive": expensive, "cheapest": cheapest},
            "energy": energy,
            "monthly_inventory": monthly_inventory,
            "bedrooms": bedrooms
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/{commune}/stats")
async def get_commune_stats(commune: str, db: AsyncSession = Depends(get_db)):
    """Get detailed listing statistics for a specific commune"""
    try:
        # Query stats directly from mv_apartment_clean_daily using commune_clean
        stats_result = await db.execute(
            text("""
                SELECT 
                    commune_clean as commune,
                    COUNT(*) FILTER (WHERE bedrooms = 1) AS bed_1,
                    COUNT(*) FILTER (WHERE bedrooms = 2) AS bed_2,
                    COUNT(*) FILTER (WHERE bedrooms = 3) AS bed_3,
                    COUNT(*) FILTER (WHERE bedrooms >= 4) AS bed_4plus,
                    COUNT(*) FILTER (WHERE area < 50) AS size_under_50,
                    COUNT(*) FILTER (WHERE area >= 50 AND area < 80) AS size_50_80,
                    COUNT(*) FILTER (WHERE area >= 80 AND area < 120) AS size_80_120,
                    COUNT(*) FILTER (WHERE area >= 120) AS size_120plus,
                    COUNT(*) FILTER (WHERE first_seen > NOW() - INTERVAL '7 days') AS age_fresh,
                    COUNT(*) FILTER (WHERE first_seen <= NOW() - INTERVAL '7 days' AND first_seen > NOW() - INTERVAL '30 days') AS age_recent,
                    COUNT(*) FILTER (WHERE first_seen <= NOW() - INTERVAL '30 days' AND first_seen > NOW() - INTERVAL '90 days') AS age_stale,
                    COUNT(*) FILTER (WHERE first_seen <= NOW() - INTERVAL '90 days') AS age_very_stale,
                    COUNT(*) FILTER (WHERE energy_class IN ('a', 'b', 'A', 'B')) AS energy_ab,
                    COUNT(*) FILTER (WHERE energy_class IN ('c', 'd', 'C', 'D')) AS energy_cd,
                    COUNT(*) FILTER (WHERE energy_class IN ('e', 'f', 'g', 'E', 'F', 'G')) AS energy_efg,
                    COUNT(*) AS total_listings
                FROM mv_apartment_clean_daily
                WHERE commune_clean = :commune AND status = 'active'
                GROUP BY commune_clean
            """),
            {"commune": commune}
        )
        stats_row = stats_result.fetchone()
        
        if not stats_row:
            raise HTTPException(status_code=404, detail=f"Commune '{commune}' not found")
        
        stats = dict(stats_row._mapping)
        
        # Query top agencies using commune_clean
        agencies_result = await db.execute(
            text("""
                SELECT agency_name, COUNT(*) as count 
                FROM mv_apartment_clean_daily
                WHERE commune_clean = :commune AND status = 'active'
                GROUP BY agency_name 
                ORDER BY count DESC 
                LIMIT 5
            """),
            {"commune": commune}
        )
        agencies = [dict(row._mapping) for row in agencies_result.fetchall()]
        
        return {"stats": stats, "agencies": agencies}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")


@router.get("/{commune}/listings")
async def get_commune_listings(
    commune: str, 
    site: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db)
):
    """Get listings for a commune with site distribution"""
    try:
        # Get site distribution
        sites_result = await db.execute(
            text("""
                SELECT site, COUNT(DISTINCT listing_fingerprint) as count 
                FROM mv_apartment_clean_daily
                WHERE commune_clean = :commune AND status = 'active'
                GROUP BY site ORDER BY count DESC
            """),
            {"commune": commune}
        )
        sites = [dict(row._mapping) for row in sites_result.fetchall()]
        
        # Get listings (filtered by site if provided), deduplicated by listing_fingerprint
        query = """
            SELECT DISTINCT ON (listing_fingerprint) 
                url, site, price, bedrooms, area, locality_clean as address, listing_fingerprint
            FROM mv_apartment_clean_daily
            WHERE commune_clean = :commune AND status = 'active'
        """
        params = {"commune": commune}
        
        if site:
            query += " AND site = :site"
            params["site"] = site
        
        query += " ORDER BY listing_fingerprint, price ASC"
        
        listings_result = await db.execute(text(query), params)
        rows = [dict(row._mapping) for row in listings_result.fetchall()]
        # Sort by price and limit after dedup
        listings = sorted(rows, key=lambda x: x.get('price') or 0)[:100]
        
        return {"sites": sites, "listings": listings}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Database error: {str(e)}")
