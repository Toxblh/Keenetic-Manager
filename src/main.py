# main.py
import os
if os.environ.get("DEBUG") == "1":
    import debugpy
    debugpy.listen(('127.0.0.1', 9002))
    debugpy.wait_for_client()
    # debugpy.breakpoint()

import os
import sys
from .router_manager_app import RouterManagerApplication


def main(version):
    app = RouterManagerApplication(version)
    return app.run(sys.argv)


if __name__ == "__main__":
    main()
