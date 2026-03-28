from setuptools import setup, find_packages

setup(
    name="atlas-dev",
    version="0.1.0",
    description="A SwissEph interface for visualizing astrological/astronomical data.",
    author="clairaut",
    packages=find_packages(),
    package_data={"atlas_dev": ["src/view/shaders/*.vert", "src/view/shaders/*.frag"]},
    install_requires=[
        "pyswisseph",
        "rich",
        "timezonefinder",
        "pytz",
        "moderngl",
        "moderngl-window",
        "Pillow",
        "numpy",
        "glfw",
    ],
    entry_points={
        "console_scripts": [
            "atlas=atlas_dev.src.cli:main"
        ]
    },
    python_requires=">=3.9",
    include_package_data=True,
)
