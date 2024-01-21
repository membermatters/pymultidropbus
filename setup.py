from setuptools import find_packages, setup

setup(
    name="pymultidropbus",
    packages=find_packages(include=["pymultidropbus"]),
    version="0.0.1",
    description="Implements a cashless MDB peripheral over UART",
    author="Jaimyn Mayer",
    install_requires=[
        "pyserial",
    ],
)
