import os
from loguru import logger
from fastapi import Response
from jinja2 import Environment, FileSystemLoader

DEFAULT_TEMPLATE_ENVIRONMENT = Environment(
    loader=FileSystemLoader("%s/templates/" % os.path.dirname(__file__))
)


def render_template(template_name: str, template_environment: Environment, **kwargs):
    template = template_environment.get_template(template_name)
    return template.render(**kwargs)


def get_connection_twiml(
    call_id: str,
    base_url: str,
    ssl: bool = True,
    template_environment: Environment = DEFAULT_TEMPLATE_ENVIRONMENT,
):
    protocol = "wss" if ssl == True else "ws"
    url = f"{protocol}://{base_url}/connect_call/{call_id}"
    logger.info(f"Getting connection twiml for call {call_id} with url: {url}")
    return Response(
        render_template(
            template_name="twilio_connect_call.xml",
            template_environment=template_environment,
            url=url,
        ),
        media_type="application/xml",
    )
