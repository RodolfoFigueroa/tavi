import logging
import os

import sqlalchemy
from langchain_anthropic import ChatAnthropic
from lyra_api import LyraAPIClient

LYRA_HOST = os.environ.get("LYRA_HOST", "localhost:5219")
lyra_client = LyraAPIClient(
    host=LYRA_HOST,
    timeout=60,
    headers={
        "P-Access-Token-Id": os.environ["PANGOLIN_ACCESS_TOKEN_ID"],
        "P-Access-Token": os.environ["PANGOLIN_ACCESS_TOKEN"],
    },
    log_level=logging.INFO,
    secure=not LYRA_HOST.startswith("localhost"),
)


engine = sqlalchemy.create_engine(
    f"postgresql://{os.environ['POSTGRES_USER']}:{os.environ['POSTGRES_PASSWORD']}@{os.environ['POSTGRES_HOST']}:{os.environ['POSTGRES_PORT']}/{os.environ['POSTGRES_DB']}"
)

base_llm = ChatAnthropic(model="claude-sonnet-4-6")  # ty:ignore[missing-argument, unknown-argument]
