from setuptools import setup, find_packages

setup(
    name="atlas",
    version="0.2.9",
    description="A SwissEph interface for visualizing astrological/astronomical data.",
    author="clairaut",
    package_dir={"": "src"},
    packages=find_packages(where="src"),
    package_data={"atlas": ["view/shaders/*.vert", "view/shaders/*.frag", "data/*.dat", "data/*.npy"]},
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
            "atlas=atlas.cli:main"
        ]
    },
    python_requires=">=3.9",
    include_package_data=True,
)
