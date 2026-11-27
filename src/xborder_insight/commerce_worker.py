"""Periodic expiry; restart-safe because order transitions are transactional."""
import asyncio
import logging
import os
import sqlite3

from . import commerce
from .errors import DbNotReady

logger=logging.getLogger(__name__)


def sweep(open_db):
    with open_db() as conn:
        tenants=conn.execute("SELECT DISTINCT tenant FROM commerce_orders WHERE status='pending'").fetchall()
        return sum(commerce.expire(conn,t['tenant']) for t in tenants)


async def serve(open_db,stop,interval=None):
    if interval is None:
        try:
            interval=max(1,min(3600,float(os.getenv('COMMERCE_EXPIRY_INTERVAL','30'))))
        except ValueError:
            interval=30
    while not stop.is_set():
        try:
            count=await asyncio.to_thread(sweep,open_db)
            if count:
                logger.info('commerce.expired count=%d',count)
        except (DbNotReady,sqlite3.Error):
            # Keep the app observable when migrations have not been applied.
            logger.warning('commerce.expiry_skipped: database unavailable or schema pending')
        try:
            await asyncio.wait_for(stop.wait(),timeout=interval)
        except TimeoutError:
            pass
