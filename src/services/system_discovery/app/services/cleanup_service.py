import asyncio
import logging
import shutil
import time
from pathlib import Path

logger = logging.getLogger("cleanup_service")

STORAGE_DIR = Path("storage")

async def clean_old_storage(max_age_seconds: int = 86400):
    """
    Cleans up directories and files in STORAGE_DIR that are older than max_age_seconds.
    By default, deletes items older than 24 hours.
    """
    if not STORAGE_DIR.exists():
        return

    now = time.time()
    logger.info("Starting storage cleanup process...")
    
    deleted_count = 0
    for path in STORAGE_DIR.iterdir():
        try:
            mtime = path.stat().st_mtime
            age = now - mtime
            if age > max_age_seconds:
                logger.info(f"Removing old storage item: {path.name} (age: {age/3600:.1f} hours)")
                if path.is_dir():
                    shutil.rmtree(path)
                else:
                    path.unlink()
                deleted_count += 1
        except Exception as e:
            logger.error(f"Failed to delete {path}: {e}")
            
    if deleted_count > 0:
        logger.info(f"Successfully cleaned up {deleted_count} items from storage.")
    else:
        logger.info("Storage cleanup complete. No items were eligible for deletion.")

async def start_periodic_cleanup(interval_seconds: int = 86400):
    """
    Periodic loop that runs cleanup every interval_seconds (default 24 hours).
    """
    while True:
        try:
            await clean_old_storage()
        except Exception as e:
            logger.error(f"Error during periodic storage cleanup: {e}")
        
        await asyncio.sleep(interval_seconds)
