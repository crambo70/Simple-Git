"""
py2app build script for Simple Git.

Build a distributable .app:
    pip install py2app
    python setup.py py2app

For a quick local test (symlinks instead of copying):
    python setup.py py2app -A
"""

from setuptools import setup

APP     = ["simple_git.py"]
DATA    = ["config.json"]          # bundled as a writable template
OPTIONS = {
    "argv_emulation": False,       # True can cause issues on newer macOS
    "iconfile": "icon.icns",
    "plist": {
        "CFBundleName":             "Santina's Tool",
        "CFBundleDisplayName":      "Santina's Tool",
        "CFBundleIdentifier":       "com.santinatool.app",
        "CFBundleVersion":          "1.0.0",
        "CFBundleShortVersionString": "1.0",
        "NSHighResolutionCapable":  True,
    },
    "packages": [],                # all deps are stdlib; nothing extra needed
}

setup(
    name="Santina's Tool",
    app=APP,
    data_files=DATA,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
