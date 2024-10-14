# main.py
import os
import sys
from .router_manager_app import RouterManagerApplication

def main(version):
    app = RouterManagerApplication()
    return app.run(sys.argv)

if __name__ == "__main__":
    main()