"""Use the browser and Node driver shipped with this portable build."""

import os

os.environ["PLAYWRIGHT_BROWSERS_PATH"] = "0"
os.environ.pop("PLAYWRIGHT_NODEJS_PATH", None)
