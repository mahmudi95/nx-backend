from motor.motor_asyncio import AsyncIOMotorClient
import os

# MongoDB connection
mongo_client = AsyncIOMotorClient(
    f"mongodb://{os.getenv('MONGODB_USERNAME')}:{os.getenv('MONGODB_PASSWORD')}@mongodb:27017"
)
mongo_db = mongo_client[os.getenv('MONGODB_DB', 'neuraplex')]

async def get_mongo_db():
    """Dependency for FastAPI routes"""
    return mongo_db
