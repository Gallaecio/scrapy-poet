from typing import Any, Sequence, Set, Callable

import attr
import pytest
from pytest_twisted import inlineCallbacks
import weakref

import parsel
from scrapy import Request
from scrapy.http import Response
from url_matcher import Patterns

from url_matcher.util import get_domain

from scrapy_poet import CacheDataProviderMixin, HttpResponseProvider, PageObjectInputProvider, \
    DummyResponse
from scrapy_poet.injection import check_all_providers_are_callable, is_class_provided_by_any_provider_fn, \
    get_injector_for_testing, get_response_for_testing
from scrapy_poet.injection_errors import NonCallableProviderError, \
    InjectionError, UndeclaredProvidedTypeError
from scrapy_poet.overrides import OverridesRegistry
from web_poet import Injectable, ItemPage
from web_poet.mixins import ResponseShortcutsMixin
from web_poet.overrides import OverrideRule


def get_provider(classes, content=None):
    class Provider(PageObjectInputProvider):
        provided_classes = classes
        require_response = False

        def __init__(self, crawler):
            self.crawler = crawler

        def __call__(self, to_provide):
            return [cls(content) if content else cls() for cls in classes]

    return Provider


def get_provider_requiring_response(classes):
    class Provider(PageObjectInputProvider):
        provided_classes = classes
        require_response = True

        def __init__(self, crawler):
            self.crawler = crawler

        def __call__(self, to_provide, response: Response):
            return [cls() for cls in classes]

    return Provider


class ClsReqResponse(str):
    pass


class Cls1(str):
    pass


class Cls2(str):
    pass


class ClsNoProvided(str):
    pass


class ClsNoProviderRequired(Injectable, str):
    pass


def get_providers_for_testing():
    prov1 = get_provider_requiring_response({ClsReqResponse})
    prov2 = get_provider({Cls1, Cls2})
    # Duplicating them because they should work even in this situation
    return {prov1: 1,
            prov2: 2,
            prov1: 3,
            prov2: 4}


@pytest.fixture
def providers():
    return get_providers_for_testing()


@pytest.fixture
def injector(providers):
    return get_injector_for_testing(providers)


@attr.s(auto_attribs=True, frozen=True, eq=True, order=True)
class WrapCls(Injectable):
    a: ClsReqResponse


class TestInjector:

    def test_constructor(self):
        injector = get_injector_for_testing(get_providers_for_testing())
        assert injector.is_class_provided_by_any_provider(ClsReqResponse)
        assert injector.is_class_provided_by_any_provider(Cls1)
        assert not injector.is_class_provided_by_any_provider(ClsNoProvided)

        for provider in injector.providers:
            assert (injector.is_provider_requiring_scrapy_response[provider] ==
                    provider.require_response)

        # Asserting that we are not leaking providers references
        weak_ref = weakref.ref(injector.providers[0])
        assert weak_ref()
        del injector
        assert weak_ref() is None

    def test_non_callable_provider_error(self):
        """Checks that a exception is raised when a provider is not callable"""
        class NonCallableProvider(PageObjectInputProvider):
            pass

        with pytest.raises(NonCallableProviderError):
            get_injector_for_testing({NonCallableProvider: 1})

    def test_discover_callback_providers(self, injector, providers, request):
        def discover_fn(callback):
            request = Request("http://example.com", callback=callback)
            return injector.discover_callback_providers(request)

        providers_list = list(providers.keys())

        def callback_0(a: ClsNoProvided):
            pass

        assert set(map(type, discover_fn(callback_0))) == set()

        def callback_1(a: ClsReqResponse, b: Cls2):
            pass

        assert set(map(type, discover_fn(callback_1))) == set(providers_list)

        def callback_2(a: Cls1, b: Cls2):
            pass

        assert set(map(type, discover_fn(callback_2))) == {providers_list[1]}

        def callback_3(a: ClsNoProvided, b: WrapCls):
            pass

        assert set(map(type, discover_fn(callback_3))) == {providers_list[0]}

    def test_is_scrapy_response_required(self, injector):

        def callback_no_1(response: DummyResponse, a: Cls1):
            pass

        response = get_response_for_testing(callback_no_1)
        assert not injector.is_scrapy_response_required(response.request)

        def callback_yes_1(response, a: Cls1):
            pass

        response = get_response_for_testing(callback_yes_1)
        assert injector.is_scrapy_response_required(response.request)

        def callback_yes_2(response: DummyResponse, a: ClsReqResponse):
            pass

        response = get_response_for_testing(callback_yes_2)
        assert injector.is_scrapy_response_required(response.request)

    @inlineCallbacks
    def test_build_instances_methods(self, injector):

        def callback(response: DummyResponse,
                     a: Cls1,
                     b: Cls2,
                     c: WrapCls,
                     d: ClsNoProviderRequired):
            pass

        response = get_response_for_testing(callback)
        request = response.request
        plan = injector.build_plan(response.request)
        instances = yield from injector.build_instances(request, response, plan)
        assert instances == {
            Cls1: Cls1(),
            Cls2: Cls2(),
            WrapCls: WrapCls(ClsReqResponse()),
            ClsReqResponse: ClsReqResponse(),
            ClsNoProviderRequired: ClsNoProviderRequired()
        }

        instances = yield from injector.build_instances_from_providers(
            request, response, plan)
        assert instances == {
            Cls1: Cls1(),
            Cls2: Cls2(),
            ClsReqResponse: ClsReqResponse(),
        }

    @inlineCallbacks
    def test_build_instances_from_providers_unexpected_return(self):

        class WrongProvider(get_provider({Cls1})):
            def __call__(self, to_provide):
                return super().__call__(to_provide) + [Cls2()]

        injector = get_injector_for_testing({WrongProvider: 0})

        def callback(response: DummyResponse, a: Cls1):
            pass

        response = get_response_for_testing(callback)
        plan = injector.build_plan(response.request)
        with pytest.raises(UndeclaredProvidedTypeError) as exinf:
            yield from injector.build_instances_from_providers(
            response.request, response, plan)

        assert "Provider" in str(exinf.value)
        assert "Cls2" in str(exinf.value)
        assert "Cls1" in str(exinf.value)

    @pytest.mark.parametrize("str_list", [
        ["1", "2", "3"],
        ["3", "2", "1"],
        ["1", "3", "2"],
    ])
    @inlineCallbacks
    def test_build_instances_from_providers_respect_priorities(
            self, str_list):
        providers = {get_provider({str}, text): int(text) for text in str_list}
        injector = get_injector_for_testing(providers)

        def callback(response: DummyResponse, arg: str):
            pass

        response = get_response_for_testing(callback)
        plan = injector.build_plan(response.request)
        instances = yield from injector.build_instances_from_providers(
            response.request, response, plan)

        assert instances[str] == min(str_list)

    @inlineCallbacks
    def test_build_callback_dependencies(self, injector):
        def callback(response: DummyResponse,
                     a: Cls1,
                     b: Cls2,
                     c: WrapCls,
                     d: ClsNoProviderRequired):
            pass

        response = get_response_for_testing(callback)
        kwargs = yield from injector.build_callback_dependencies(
            response.request, response)
        kwargs_types = {key: type(value) for key, value in kwargs.items()}
        assert kwargs_types == {
            "a": Cls1,
            "b": Cls2,
            "c": WrapCls,
            "d": ClsNoProviderRequired
        }


class Html(Injectable):
    url = "http://example.com"
    html = """<html><body>Price: <span class="price">22</span>€</body></html>"""

    @property
    def selector(self):
        return parsel.Selector(self.html)


class EurDollarRate(Injectable):
    rate = 1.1


class OtherEurDollarRate(Injectable):
    rate = 2


@attr.s(auto_attribs=True)
class PricePO(ItemPage, ResponseShortcutsMixin):
    response: Html

    def to_item(self):
        return dict(price=float(self.css(".price::text").get()), currency="€")


@attr.s(auto_attribs=True)
class PriceInDollarsPO(ItemPage):
    original_po: PricePO
    conversion: EurDollarRate

    def to_item(self):
        item = self.original_po.to_item()
        item["price"] *= self.conversion.rate
        item["currency"] = "$"
        return item


class TestInjectorOverrides:

    @pytest.mark.parametrize("override_should_happen", [True, False])
    @inlineCallbacks
    def test_overrides(self, providers, override_should_happen):
        domain = "example.com" if override_should_happen else "other-example.com"
        # The request domain is example.com, so overrides shouldn't be applied
        # when we configure them for domain other-example.com
        overrides = [
            (domain, PriceInDollarsPO, PricePO),
            OverrideRule(Patterns([domain]), use=OtherEurDollarRate, instead_of=EurDollarRate)
        ]
        registry = OverridesRegistry(overrides)
        injector = get_injector_for_testing(providers,
                                            overrides_registry=registry)

        def callback(response: DummyResponse, price_po: PricePO, rate_po: EurDollarRate):
            pass

        response = get_response_for_testing(callback)
        kwargs = yield from injector.build_callback_dependencies(
            response.request, response)
        kwargs_types = {key: type(value) for key, value in kwargs.items()}
        price_po = kwargs["price_po"]
        item = price_po.to_item()

        if override_should_happen:
            assert kwargs_types == {"price_po": PriceInDollarsPO, "rate_po": OtherEurDollarRate}
            # Note that OtherEurDollarRate don't have effect inside PriceInDollarsPO
            # because composability of overrides is forbidden
            assert item == {"price": 22 * 1.1, "currency": "$"}
        else:
            assert kwargs_types == {"price_po": PricePO, "rate_po": EurDollarRate}
            assert item == {"price": 22, "currency": "€"}


def test_load_provider_classes():
    provider_as_string = f"{HttpResponseProvider.__module__}.{HttpResponseProvider.__name__}"
    injector = get_injector_for_testing({provider_as_string: 2, HttpResponseProvider: 1})
    assert all(type(prov) == HttpResponseProvider for prov in injector.providers)
    assert len(injector.providers) == 2


def test_check_all_providers_are_callable():
    check_all_providers_are_callable([HttpResponseProvider(None)])
    with pytest.raises(NonCallableProviderError) as exinf:
        check_all_providers_are_callable([PageObjectInputProvider(None),
                                          HttpResponseProvider(None)])

    assert "PageObjectInputProvider" in str(exinf.value)
    assert "not callable" in str(exinf.value)

def test_is_class_provided_by_any_provider_fn():
    providers = [get_provider({str}),
                 get_provider(lambda x: issubclass(x, InjectionError)),
                 get_provider(frozenset({int, float})),
                 ]
    is_provided = is_class_provided_by_any_provider_fn(providers)
    is_provided_empty = is_class_provided_by_any_provider_fn([])

    for cls in [str, InjectionError, NonCallableProviderError, int, float]:
        assert is_provided(cls)
        assert not is_provided_empty(cls)

    for cls in [bytes, Exception]:
        assert not is_provided(cls)
        assert not is_provided_empty(cls)

    class WrongProvider(PageObjectInputProvider):
        provided_classes = [str]  # Lists are not allowed, only sets or funcs

    with pytest.raises(InjectionError):
        is_class_provided_by_any_provider_fn([WrongProvider])


def get_provider_for_cache(classes, a_name, content=None, error=ValueError):
    class Provider(PageObjectInputProvider, CacheDataProviderMixin):
        name = a_name
        provided_classes = classes
        require_response = False

        def __init__(self, crawler):
            self.crawler = crawler

        def __call__(self, to_provide, request: Request):
            if not get_domain(request.url) == "example.com":
                raise error("The URL is not from example.com")
            return [cls(content) if content else cls() for cls in classes]

        def fingerprint(self, to_provide: Set[Callable], request: Request) -> str:
            return request.url

        def serialize(self, result: Sequence[Any]) -> Any:
            return result

        def deserialize(self, data: Any) -> Sequence[Any]:
            return data

    return Provider


@pytest.mark.parametrize("cache_errors", [True, False])
@inlineCallbacks
def test_cache(tmp_path, cache_errors):
    """
    In a first run, the cache is empty, and two requests are done, one with exception.
    In the second run we should get the same result as in the first run. The
    behaviour for exceptions vary if caching errors is disabled.
    """

    def validate_instances(instances):
        assert instances[str] == "foo"
        assert instances[int] == 3
        assert instances[float] == 3.0

    providers = {
        get_provider_for_cache({str}, "str", content="foo"): 1,
        get_provider_for_cache({int, float}, "number", content=3): 2,
    }

    cache = tmp_path / "cache3.sqlite3"
    if cache.exists():
        print(f"Cache file {cache} already exists. Weird. Deleting")
        cache.unlink()
    settings = {"SCRAPY_POET_CACHE": cache,
                "SCRAPY_POET_CACHE_ERRORS": cache_errors}
    injector = get_injector_for_testing(providers, settings)
    assert cache.exists()

    def callback(response: DummyResponse, arg_str: str, arg_int: int, arg_float: float):
        pass

    response = get_response_for_testing(callback)
    plan = injector.build_plan(response.request)
    instances = yield from injector.build_instances_from_providers(
        response.request, response, plan)

    validate_instances(instances)

    # Changing the request URL below would result in the following error:
    #   <twisted.python.failure.Failure builtins.ValueError: The URL is not from
    #   example.com>>
    response.request = Request.replace(response.request, url="http://willfail.page")
    with pytest.raises(ValueError):
        plan = injector.build_plan(response.request)
        instances = yield from injector.build_instances_from_providers(
            response.request, response, plan)

    # Different providers. They return a different result, but the cache data should prevail.
    providers = {
        get_provider_for_cache({str}, "str", content="bar", error=KeyError): 1,
        get_provider_for_cache({int, float}, "number", content=4, error=KeyError): 2,
    }
    injector = get_injector_for_testing(providers, settings)

    response = get_response_for_testing(callback)
    plan = injector.build_plan(response.request)
    instances = yield from injector.build_instances_from_providers(
        response.request, response, plan)

    validate_instances(instances)

    # If caching errors is disabled, then KeyError should be raised.
    Error = ValueError if cache_errors else KeyError
    response.request = Request.replace(response.request, url="http://willfail.page")
    with pytest.raises(Error):
        plan = injector.build_plan(response.request)
        instances = yield from injector.build_instances_from_providers(
            response.request, response, plan)
