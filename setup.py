from setuptools import setup, find_packages

setup(
    name="superbot",
    version="0.1.0",
    packages=find_packages(),
    install_requires=[
        "aiogram>=3.0.0",
        "python-dotenv>=0.19.0",
        "sqlalchemy>=2.0.0",
        "asyncpg>=0.27.0",
        "openai>=1.0.0",
        "emoji>=2.2.0",
        "pydantic>=2.0.0",
        "pydantic-settings>=2.0.0",
        "python-dateutil>=2.8.2",
        "pytz>=2023.3",
        "greenlet>=3.1.1",
    ],
) 