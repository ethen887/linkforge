from setuptools import find_packages, setup

setup(
    name="linkforge",
    version="0.1.0",
    description="Modular automation framework connecting web, code, AI models, and workflows",
    packages=find_packages(where="src"),
    package_dir={"": "src"},
    python_requires=">=3.9",
    install_requires=[
        "openai>=1.0.0",
        "anthropic>=0.20.0",
        "requests>=2.28.0",
    ],
    extras_require={
        "dev": [
            "pytest>=7.0",
            "pytest-cov>=4.0",
            "ruff>=0.1.0",
            "mypy>=1.0",
        ],
    },
    entry_points={
        "console_scripts": [
            "linkforge=linkforge.cli:main",
        ],
    },
)
