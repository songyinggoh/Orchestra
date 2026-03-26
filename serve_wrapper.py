import os

from orchestra.server.app import create_app
from orchestra.server.config import ServerConfig

host = os.environ.get("ORCHESTRA_HOST", "0.0.0.0")
port = int(os.environ.get("ORCHESTRA_PORT", "8000"))
config = ServerConfig(host=host, port=port)
app = create_app(config)

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=host, port=port)
