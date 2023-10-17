"""Global variables"""

import pathlib

root_path = pathlib.Path(__file__).parent.parent.resolve()


if __name__ == "__main__":
    print(f"rootPath = {root_path}")
