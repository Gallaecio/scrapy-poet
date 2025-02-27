"""An important part of scrapy-poet is the Injection Middleware. It's
responsible for injecting Page Input dependencies before the request callbacks
are executed.
"""
import logging
from typing import Optional, Type, TypeVar

from scrapy import Spider, signals
from scrapy.crawler import Crawler
from scrapy.http import Request, Response
from twisted.internet.defer import inlineCallbacks

from scrapy.utils.misc import create_instance, load_object

from .api import DummyResponse
from .overrides import OverridesRegistry
from .page_input_providers import HttpResponseProvider
from .injection import Injector


logger = logging.getLogger(__name__)


DEFAULT_PROVIDERS = {
    HttpResponseProvider: 500
}

InjectionMiddlewareTV = TypeVar("InjectionMiddlewareTV", bound="InjectionMiddleware")


class InjectionMiddleware:
    """This is a Downloader Middleware that's supposed to:

    * check if request downloads could be skipped
    * inject dependencies before request callbacks are executed
    """
    def __init__(self, crawler: Crawler) -> None:
        """Initialize the middleware"""
        self.crawler = crawler
        settings = self.crawler.settings
        registry_cls = load_object(settings.get("SCRAPY_POET_OVERRIDES_REGISTRY",
                                                OverridesRegistry))
        self.overrides_registry = create_instance(registry_cls, settings, crawler)
        self.injector = Injector(crawler,
                                 default_providers=DEFAULT_PROVIDERS,
                                 overrides_registry=self.overrides_registry)

    @classmethod
    def from_crawler(cls: Type[InjectionMiddlewareTV], crawler: Crawler) -> InjectionMiddlewareTV:
        o = cls(crawler)
        crawler.signals.connect(o.spider_closed, signal=signals.spider_closed)
        return o

    def spider_closed(self, spider: Spider) -> None:
        self.injector.close()

    def process_request(self, request: Request, spider: Spider) -> Optional[DummyResponse]:
        """This method checks if the request is really needed and if its
        download could be skipped by trying to infer if a ``Response``
        is going to be used by the callback or a Page Input.

        If the ``Response`` can be ignored, a ``utils.DummyResponse`` object is
        returned on its place. This ``DummyResponse`` is linked to the original
        ``Request`` instance.

        With this behavior, we're able to optimize spider executions avoiding
        unnecessary downloads. That could be the case when the callback is
        actually using another source like external APIs such as Zyte's
        AutoExtract.
        """
        if self.injector.is_scrapy_response_required(request):
            return None

        logger.debug(f"Using DummyResponse instead of downloading {request}")
        return DummyResponse(url=request.url, request=request)

    @inlineCallbacks
    def process_response(self, request: Request, response: Response,
                         spider: Spider) -> Response:
        """This method fills ``request.cb_kwargs`` with instances for
        the required Page Objects found in the callback signature.

        In other words, this method instantiates all ``Injectable``
        subclasses declared as request callback arguments and
        any other parameter with a ``PageObjectInputProvider`` configured for
        its type.

        If there's a collision between an already set ``cb_kwargs``
        and an injectable attribute,
        the user-defined ``cb_kwargs`` takes precedence.
        """
        # Find out the dependencies
        final_kwargs = yield from self.injector.build_callback_dependencies(
            request,
            response
        )
        # Fill the callback arguments with the created instances
        for arg, value in final_kwargs.items():
            # Precedence of user callback arguments
            if arg not in request.cb_kwargs:
                request.cb_kwargs[arg] = value
            # TODO: check if all arguments are fulfilled somehow?

        return response
