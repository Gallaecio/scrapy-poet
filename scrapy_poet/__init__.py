from .api import AnnotatedResult, DummyResponse, callback_for
from .downloadermiddlewares import DownloaderStatsMiddleware, InjectionMiddleware
from .page_input_providers import HttpResponseProvider, PageObjectInputProvider
from .spidermiddlewares import RetryMiddleware
from ._request_fingerprinter import ScrapyPoetRequestFingerprinter
