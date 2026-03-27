from __future__ import annotations
import asyncio
import logging
from datetime import datetime

import aiohttp
from fastapi import FastAPI
from fastapi.responses import JSONResponse
import uvicorn

from core.config import PORT, BOT_TOKEN, START_PIC_URL
from core.client import client
from core.utils import download_start_pic_if_not_exists, get_fixed_thumbnail
from core.handlers import register_handlers
from core.scheduler import setup_scheduler

logger = logging.getLogger(__name__)
health_logger = logging.getLogger('health_monitor')

app = FastAPI()


@app.get("/health")
async def health_check():
    return JSONResponse(
        status_code=200,
        content={"status": "healthy", "message": "𝙼𝚊𝚜𝚝𝚎𝚛, 𝚢𝚘𝚞𝚛 𝚜𝚎𝚛𝚟𝚊𝚗𝚝 𝚒𝚜 𝚘𝚗𝚌𝚎 𝚊𝚐𝚊𝚒𝚗 𝚊𝚕𝚒𝚟𝚎.― 𝙼𝚒𝚛𝚊𝚐𝚎 𝙱𝚘𝚝𝚜"}
    )


async def _health_monitor_loop():
    health_url = f"http://127.0.0.1:{PORT}/health"
    consecutive_failures = 0
    
    await asyncio.sleep(30)
    health_logger.info(f"Health monitor started - pinging {health_url} every 60s")
    
    while True:
        try:
            async with aiohttp.ClientSession() as session:
                async with session.get(health_url, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status == 200:
                        data = await resp.json()
                        consecutive_failures = 0
                        health_logger.debug(
                            f"Health OK: status={resp.status}, "
                            f"response={data.get('status', 'unknown')}, "
                            f"time={datetime.now().strftime('%H:%M:%S')}"
                        )
                    else:
                        consecutive_failures += 1
                        health_logger.warning(
                            f"Health WARN: status={resp.status}, "
                            f"consecutive_failures={consecutive_failures}, "
                            f"time={datetime.now().strftime('%H:%M:%S')}"
                        )
        except asyncio.CancelledError:
            health_logger.info("Health monitor cancelled")
            return
        except Exception as e:
            consecutive_failures += 1
            health_logger.error(
                f"Health FAIL: error={str(e)}, "
                f"consecutive_failures={consecutive_failures}, "
                f"time={datetime.now().strftime('%H:%M:%S')}"
            )

        if consecutive_failures >= 3:
            health_logger.error(
                f"Health CRITICAL: {consecutive_failures} consecutive failures - service may be down"
            )
        
        await asyncio.sleep(60)


async def main():
    try:

        server = uvicorn.Server(uvicorn.Config(app, host="0.0.0.0", port=PORT, log_level="info"))
        asyncio.create_task(server.serve())
        
        register_handlers()
        
        await client.start(bot_token=BOT_TOKEN)
        logger.info("𝙇𝙤𝙖𝙙𝙞𝙣𝙜.")
        await asyncio.sleep(1)
        logger.info("𝙇𝙤𝙖𝙙𝙞𝙣𝙜..")
        await asyncio.sleep(1.5)
        logger.info("𝙇𝙤𝙖𝙙𝙞𝙣𝙜...")
        setup_scheduler(client)
        
        asyncio.create_task(_health_monitor_loop())
        
        await asyncio.sleep(3)
        logger.info("𝘼𝙪𝙩𝙤𝘼𝙣𝙞𝙢𝙚 𝙞𝙨 𝘼𝙇𝙄𝙑𝙀!")
        
        start_pic_path = download_start_pic_if_not_exists(START_PIC_URL)
        await get_fixed_thumbnail()

        await client.run_until_disconnected()
    except Exception as e:
        logger.error(f"𝙀𝙧𝙧𝙤𝙧: {e}")
        logger.info("𝙍𝙚:𝙎𝙩𝙖𝙧𝙩𝙞𝙣𝙜")
        await asyncio.sleep(15)
        await main()


if __name__ == '__main__':
    asyncio.run(main())
