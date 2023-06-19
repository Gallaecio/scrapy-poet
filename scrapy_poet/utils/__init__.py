import os
from functools import lru_cache
from typing import Any, Callable, List, Type
from warnings import warn

from packaging.version import Version
from scrapy import __version__ as SCRAPY_VERSION
from scrapy.crawler import Crawler
from scrapy.http import Request, Response
from scrapy.utils.project import inside_project, project_data_dir
from web_poet import (
    HttpRequest,
    HttpResponse,
    HttpResponseHeaders,
    consume_modules,
    default_registry,
)


def get_scrapy_data_path(createdir: bool = True, default_dir: str = ".scrapy") -> str:
    """Return a path to a folder where Scrapy is storing data.

    Usually that's a .scrapy folder inside the project.
    """
    # This code is extracted from scrapy.utils.project.data_path function,
    # which does too many things.
    path = project_data_dir() if inside_project() else default_dir
    if createdir:
        os.makedirs(path, exist_ok=True)
    return path


def http_request_to_scrapy_request(request: HttpRequest, **kwargs) -> Request:
    return Request(
        url=str(request.url),
        method=request.method,
        headers=request.headers,
        body=request.body,
        **kwargs,
    )


def scrapy_response_to_http_response(response: Response) -> HttpResponse:
    """Convenience method to convert a ``scrapy.http.Response`` into a
    ``web_poet.HttpResponse``.
    """
    kwargs = {}
    encoding = getattr(response, "_encoding", None)
    if encoding:
        kwargs["encoding"] = encoding
    return HttpResponse(
        url=response.url,
        body=response.body,
        status=response.status,
        headers=HttpResponseHeaders.from_bytes_dict(response.headers),
        **kwargs,
    )


def create_registry_instance(cls: Type, crawler: Crawler):
    for module in crawler.settings.getlist("SCRAPY_POET_DISCOVER", []):
        consume_modules(module)
    if "SCRAPY_POET_OVERRIDES" in crawler.settings:
        msg = (
            "The SCRAPY_POET_OVERRIDES setting is deprecated. "
            "Use SCRAPY_POET_RULES instead."
        )
        warn(msg, DeprecationWarning, stacklevel=2)
    rules = crawler.settings.getlist(
        "SCRAPY_POET_RULES",
        crawler.settings.getlist("SCRAPY_POET_OVERRIDES", default_registry.get_rules()),
    )
    return cls(rules=rules)


@lru_cache()
def is_min_scrapy_version(version: str) -> bool:
    return Version(SCRAPY_VERSION) >= Version(version)


def get_registered_anotations(generic_func: Callable) -> List[Any]:
    """Get argument annotations from all registered functions for a given generic function"""
    registered_funcs: List[Callable] = list(generic_func.registry.values())  # type: ignore[attr-defined]
    registered_annotations = []
    for func in registered_funcs:
        # get all parameter annotations, except from the return value
        # `inspect.get_annotations()` could be a better option but it's not compatible with python<3.10
        annotations = list(func.__annotations__.values())[:-1]
        registered_annotations += annotations

    return registered_annotations
