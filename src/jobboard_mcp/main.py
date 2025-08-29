import asyncio
import os
from dotenv import load_dotenv
from .logging_config import setup_logging
from .server import JobBoardServer

def run():
    load_dotenv()
    setup_logging()
    asyncio.run(_amain())

async def _amain():
    server = JobBoardServer()
    await server.run_stdio()

if __name__ == "__main__":
    run()