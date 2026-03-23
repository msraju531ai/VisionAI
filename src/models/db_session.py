from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from config.settings import settings
from src.models.database import Base, Camera

engine = create_async_engine(settings.database_url, echo=(settings.app_env == "development"))
async_session_factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    async with async_session_factory() as session:
        count = (await session.execute(select(func.count(Camera.id)))).scalar() or 0
        if count == 0:
            session.add_all(
                [
                    Camera(
                        name="Public Demo Cam 1",
                        location="Public Demo",
                        rtsp_url="https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/BigBuckBunny.mp4",
                        is_active=True,
                    ),
                    Camera(
                        name="Public Demo Cam 2",
                        location="Public Demo",
                        rtsp_url="https://commondatastorage.googleapis.com/gtv-videos-bucket/sample/ElephantsDream.mp4",
                        is_active=True,
                    ),
                ]
            )
            await session.commit()


async def get_db() -> AsyncSession:
    async with async_session_factory() as session:
        yield session
