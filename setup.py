"""py2app build configuration for Sony XM6 Controller.

Build:
    pip install py2app
    python setup.py py2app

The resulting .app bundle is in dist/Sony XM6 Controller.app
"""

from setuptools import setup

APP = ["app.py"]

DATA_FILES = [
    ("templates", ["templates/index.html"]),
    ("static", ["static/style.css", "static/app.js"]),
]

OPTIONS = {
    "argv_emulation": False,
    "packages": ["protocol", "bluetooth"],
    "includes": [
        "flask",
        "objc",
        "Foundation",
        "AppKit",
        "IOBluetooth",
        "CoreFoundation",
    ],
    "resources": ["resources/icon.png", "resources/icon@2x.png"],
    "plist": {
        "CFBundleName": "Sony XM6 Controller",
        "CFBundleDisplayName": "Sony XM6 Controller",
        "CFBundleIdentifier": "com.sony.xm6controller",
        "CFBundleVersion": "1.0.0",
        "CFBundleShortVersionString": "1.0.0",
        "LSUIElement": True,
        "NSBluetoothAlwaysUsageDescription": (
            "This app needs Bluetooth to communicate with "
            "your Sony WH-1000XM6 headphones."
        ),
        "CFBundleIconFile": "AppIcon",
    },
    "iconfile": "resources/AppIcon.icns",
}

setup(
    name="Sony XM6 Controller",
    app=APP,
    data_files=DATA_FILES,
    options={"py2app": OPTIONS},
    setup_requires=["py2app"],
)
