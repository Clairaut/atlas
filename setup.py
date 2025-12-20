from setuptools import setup, find_packages

setup(
    name="atlas-dev",
    version="0.1.0",
    description="A SwissEph interface for visualizing astrological/astronomical data.",
    author="clairaut",
    packages=find_packages(),
    install_requires=[
        "pyswisseph",
        "rich",
        # Add other dependencies here
    ],
    entry_points={
        "console_scripts": [
            "atlas-dev=atlas.src.cli:main"
        ]
    },
    python_requires=">=3.9",
    include_package_data=True,
)
