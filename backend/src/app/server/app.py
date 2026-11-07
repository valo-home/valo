import asyncio
from importlib.metadata import version

import click
from advanced_alchemy.extensions.litestar import SQLAlchemyPlugin
from click import Group
from litestar import Litestar
from litestar.openapi import OpenAPIConfig
from litestar.plugins import CLIPluginProtocol
from sqlalchemy import select

from app.db import base as db
from app.db.models import User
from app.domain import auth, tasks
from app.domain.common import ROLES
from app.lib import log, mqtt
from app.lib.tasks import broker
from app.server.admin import admin
from app.server.base import access_log, problem
from app.server.cameras import cams
from app.server.chat import chat
from app.server.routes import core, public

_ = tasks


async def startup() -> None:
    if not broker.is_worker_process:
        await broker.startup()


async def shutdown() -> None:
    await broker.shutdown()
    await mqtt.close()


class UsersCLI(CLIPluginProtocol):
    def on_cli_init(self, cli: Group) -> None:
        @cli.group(name="users")
        def users() -> None:
            pass

        @users.command(name="create")
        @click.option("--username", required=True)
        @click.option("--name", required=True)
        @click.option("--password", required=True)
        @click.option("--role", default="owner", type=click.Choice(list(ROLES)))
        def create(username: str, name: str, password: str, role: str) -> None:
            async def run() -> None:
                async with db.session() as s:
                    await auth.ensure_owner(s, username, name, password, role)
                    await db.commit(s)

            asyncio.run(run())
            click.echo(f"user {username} {role}")

        @users.command(name="list")
        def listing() -> None:
            async def run() -> None:
                async with db.session() as s:
                    for u in (await s.scalars(select(User).order_by(User.created_at))).all():
                        click.echo(f"{u.username}\t{u.role}\t{u.name}\t{'active' if u.active else 'disabled'}")

            asyncio.run(run())


def create_app() -> Litestar:
    log.setup("backend")
    plugins: list = [SQLAlchemyPlugin(config=db.config), UsersCLI()]
    return Litestar(
        route_handlers=[public, core, admin, cams, chat],
        plugins=plugins,
        middleware=[access_log],
        exception_handlers={Exception: problem},
        on_startup=[startup],
        on_shutdown=[shutdown],
        openapi_config=OpenAPIConfig(title="Valo API", version=version("valo"), path="/api/schema"),
        request_max_body_size=4 * 1024 * 1024,
        logging_config=None,
    )


app = create_app()
